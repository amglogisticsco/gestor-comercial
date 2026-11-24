"""Prueba de punta a punta: cliente → cotización → PDF → correo → anticipo → cumpleaños."""
import re
from datetime import date
from email import message_from_bytes, policy
from pathlib import Path

import pytest

from app import create_app, db
from app.models import Anticipo, Cliente, Correo, Cotizacion
from app.services import cumpleanos


@pytest.fixture()
def cliente_http(tmp_path):
    app = create_app({
        "TESTING": True, "SECRET_KEY": "prueba", "PROGRAMADOR": False,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'p.db'}",
        "BANDEJA_PRUEBA": str(tmp_path / "bandeja"), "UPLOAD_DIR": str(tmp_path / "up"),
        "SMTP_MODO": "archivo", "SMTP_REMITENTE": "comercial@empresa.test",
    })
    c = app.test_client()
    c.app = app
    c.bandeja = tmp_path / "bandeja"
    return c


def csrf(c, url="/login"):
    html = c.get(url).get_data(as_text=True)
    return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)


def post(c, url, datos, desde=None):
    datos = {**datos, "_csrf": csrf(c, desde or url)}
    return c.post(url, data=datos, follow_redirects=True)


def test_flujo_completo(cliente_http):
    c = cliente_http
    # Primer uso: redirige a crear cuenta
    assert "/setup" in c.get("/").headers["Location"]
    r = post(c, "/setup", {"empresa": "Logística Demo SAS", "nombre": "Ana Pérez",
                           "email": "ana@demo.co", "clave": "clave-segura"})
    assert r.status_code == 200 and "Configuración" in r.get_data(as_text=True)

    # Sin CSRF se rechaza
    assert c.post("/clientes/nuevo", data={"razon_social": "X"}).status_code == 400

    hoy = date.today()
    r = post(c, "/clientes/nuevo", {
        "razon_social": "Importadora Andina SAS", "nit": "900123456-7", "contacto_nombre": "Carlos Gómez",
        "email": "carlos@andina.test", "fecha_nacimiento": hoy.replace(year=1985).isoformat(),
    })
    assert "Cliente creado" in r.get_data(as_text=True)
    with c.app.app_context():
        cliente = Cliente.query.one()
        cid = cliente.id
        assert cliente.dias_para_cumple() == 0

    # Cotización con dos ítems (uno sin IVA) y montos al estilo colombiano
    r = post(c, "/cotizaciones/nueva", {
        "cliente_id": cid, "fecha": hoy.isoformat(), "validez_dias": "15", "moneda": "COP", "iva_pct": "19",
        "tipo_operacion": "Importación", "modalidad": "Marítima", "origen": "Shanghái", "destino": "Buenaventura",
        "item_servicio": ["", ""], "item_descripcion": ["Agenciamiento aduanero", "Flete internacional marítimo"],
        "item_cantidad": ["1", "2"], "item_unidad": ["Trámite", "Contenedor"],
        "item_precio": ["1.500.000", "4.000.000"], "item_iva": ["1", "0"],
    })
    assert "COT-" in r.get_data(as_text=True)
    with c.app.app_context():
        cot = Cotizacion.query.one()
        assert cot.subtotal == 9_500_000
        assert cot.iva == 285_000
        assert cot.total == 9_785_000
        cot_id = cot.id

    pdf = c.get(f"/cotizaciones/{cot_id}/pdf")
    assert pdf.mimetype == "application/pdf" and pdf.data[:4] == b"%PDF"

    # Preparar correo: queda como borrador, NO se envía
    r = post(c, f"/cotizaciones/{cot_id}/correo", {}, desde=f"/cotizaciones/{cot_id}")
    assert "Revisar y enviar" in r.get_data(as_text=True)
    assert not c.bandeja.exists()
    with c.app.app_context():
        borrador = Correo.query.filter_by(tipo="cotizacion").one()
        assert borrador.estado == "borrador"
        bid = borrador.id

    # Enviar (modo archivo) tras la revisión
    r = post(c, f"/correos/{bid}", {"para": "carlos@andina.test", "cc": "", "asunto": borrador.asunto,
                                    "cuerpo": borrador.cuerpo, "accion": "enviar"})
    assert "guardado en la bandeja de prueba" in r.get_data(as_text=True)
    eml = list(c.bandeja.glob("*.eml"))
    assert len(eml) == 1
    msg = message_from_bytes(eml[0].read_bytes(), policy=policy.default)
    assert msg["To"] == "carlos@andina.test"
    assert "ana@demo.co" in msg["Reply-To"]  # las respuestas van al ejecutivo
    adjuntos = [p.get_filename() for p in msg.iter_attachments()]
    assert adjuntos == [f"{cot.numero}.pdf"]
    with c.app.app_context():
        assert db.session.get(Cotizacion, cot_id).estado == "enviada"

    # Aprobada → solicitud de fondos con tributos (como el Excel de AMG) y conceptos
    post(c, f"/cotizaciones/{cot_id}/estado", {"estado": "aprobada"}, desde=f"/cotizaciones/{cot_id}")
    r = post(c, f"/anticipos/nuevo?cotizacion_id={cot_id}", {
        "cotizacion_id": cot_id, "tipo_operacion": "Importación", "do_numero": "DO-123", "aduana": "Cartagena",
        "fecha": hoy.isoformat(), "fecha_limite": hoy.isoformat(),
        "trm": "3168,57", "fob": "21119,75", "flete": "305", "seguro": "80", "otros_cif": "337",
        "arancel_pct": "0", "iva_tributo_pct": "19",
        "item_grupo": ["Intermediación aduanera", "Gastos aerolínea / puerto", "Otros gastos"],
        "item_descripcion": ["Agenciamiento marítimo", "Liberación", "Movimientos bancarios"],
        "item_valor": ["850.000", "1.100.000", "65.000"],
    })
    assert "SF-" in r.get_data(as_text=True)
    with c.app.app_context():
        ant = Anticipo.query.one()
        assert ant.cif == 21841.75
        assert ant.base_gravable == round(21841.75 * 3168.57)
        assert ant.iva_tributo == round(ant.base_gravable * 0.19)
        assert ant.total == ant.iva_tributo + 2_015_000 == ant.monto
        assert [g for g, _, _ in ant.grupos] == ["Intermediación aduanera", "Gastos aerolínea / puerto", "Otros gastos"]
        assert c.get(f"/anticipos/{ant.id}/pdf").data[:4] == b"%PDF"

    # Cumpleaños: el panel prepara un único borrador (no envía, auto-envío apagado)
    assert c.get("/").status_code == 200
    c.get("/")
    with c.app.app_context():
        saludos = Correo.query.filter_by(tipo="cumpleanos").all()
        assert len(saludos) == 1 and saludos[0].estado == "borrador"
        assert "Carlos" in saludos[0].asunto
        assert cumpleanos.preparar_saludos() == []

    # Todas las páginas cargan
    for url in ["/", "/clientes/", f"/clientes/{cid}", "/clientes/nuevo", "/clientes/importar", "/servicios/",
                "/cotizaciones/", "/cotizaciones/nueva", f"/cotizaciones/{cot_id}/editar", "/anticipos/",
                "/anticipos/nuevo", f"/anticipos/nuevo?cotizacion_id={cot_id}", "/correos/", "/correos/?vista=enviados",
                f"/correos/{bid}", "/configuracion/", "/usuarios/", "/usuarios/nuevo", "/cuenta"]:
        assert c.get(url).status_code == 200, url


def test_cumple_29_febrero():
    cliente = Cliente(razon_social="X", fecha_nacimiento=date(1992, 2, 29))
    assert cliente.cumple_en(2027) == date(2027, 2, 28)
    assert cliente.cumple_en(2028) == date(2028, 2, 29)


def test_usuarios_y_permisos(cliente_http):
    c = cliente_http
    post(c, "/setup", {"empresa": "AMG", "nombre": "David Zambrano", "email": "admin@amg.test", "clave": "clave-segura"})
    # El administrador crea un usuario
    r = post(c, "/usuarios/nuevo", {"nombre": "Laura Ríos", "email": "laura@amg.test", "cargo": "Comercial",
                                    "rol": "usuario", "activo": "1", "clave": "clave-laura"})
    assert "Usuario guardado" in r.get_data(as_text=True)
    # No se puede quitar el último administrador
    with c.app.app_context():
        from app.models import Usuario
        admin_id = Usuario.query.filter_by(email="admin@amg.test").one().id
        laura_id = Usuario.query.filter_by(email="laura@amg.test").one().id
    r = post(c, f"/usuarios/{admin_id}", {"nombre": "David Zambrano", "email": "admin@amg.test", "rol": "usuario", "activo": "1"})
    assert "al menos un administrador" in r.get_data(as_text=True)

    # El usuario normal entra, pero no ve configuración ni usuarios
    post(c, "/logout", {}, desde="/")
    r = post(c, "/login", {"email": "laura@amg.test", "clave": "clave-laura"})
    assert "Usuarios</a>" not in r.get_data(as_text=True)
    assert c.get("/configuracion/").status_code == 403
    assert c.get("/usuarios/").status_code == 403
    assert c.get("/cotizaciones/nueva").status_code == 200
    # Cambia su propia contraseña
    r = post(c, "/cuenta", {"nombre": "Laura Ríos", "clave_actual": "clave-laura",
                            "clave_nueva": "nueva-clave-1", "clave_confirmar": "nueva-clave-1"})
    assert "Contraseña actualizada" in r.get_data(as_text=True)

    # El admin la desactiva y ya no puede entrar
    post(c, "/logout", {}, desde="/")
    post(c, "/login", {"email": "admin@amg.test", "clave": "clave-segura"})
    post(c, f"/usuarios/{laura_id}", {"nombre": "Laura Ríos", "email": "laura@amg.test", "rol": "usuario", "activo": "0"})
    post(c, "/logout", {}, desde="/")
    r = post(c, "/login", {"email": "laura@amg.test", "clave": "nueva-clave-1"})
    assert "desactivado" in r.get_data(as_text=True)


def test_migra_base_anterior(tmp_path):
    """Una base creada con la versión anterior recibe las columnas nuevas sin perder datos."""
    import sqlite3
    ruta = tmp_path / "vieja.db"
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE usuario (id INTEGER PRIMARY KEY, nombre VARCHAR(120) NOT NULL, email VARCHAR(160) NOT NULL UNIQUE, password_hash VARCHAR(255) NOT NULL)")
    con.execute("INSERT INTO usuario (nombre, email, password_hash) VALUES ('Ana', 'ana@x.co', 'x')")
    con.commit(); con.close()
    app = create_app({"TESTING": True, "SECRET_KEY": "x", "PROGRAMADOR": False,
                      "SQLALCHEMY_DATABASE_URI": f"sqlite:///{ruta}", "UPLOAD_DIR": str(tmp_path / "up")})
    with app.app_context():
        from app.models import Usuario
        u = Usuario.query.one()
        assert u.nombre == "Ana" and u.es_admin and u.activo


def test_cliente_exterior_sin_iva(cliente_http):
    c = cliente_http
    post(c, "/setup", {"empresa": "AMG", "nombre": "David", "email": "d@amg.test", "clave": "clave-segura"})
    post(c, "/clientes/nuevo", {"razon_social": "MODALUX INC", "pais": "Trinidad y Tobago"})
    post(c, "/clientes/nuevo", {"razon_social": "Local SAS", "pais": "Colombia"})
    with c.app.app_context():
        ext = Cliente.query.filter_by(razon_social="MODALUX INC").one()
        loc = Cliente.query.filter_by(razon_social="Local SAS").one()
        assert ext.es_exterior and not loc.es_exterior
        ext_id, loc_id = ext.id, loc.id
    assert 'name="iva_pct" id="iva_pct" value="0"' in c.get(f"/cotizaciones/nueva?cliente_id={ext_id}").get_data(as_text=True)
    assert 'name="iva_pct" id="iva_pct" value="19"' in c.get(f"/cotizaciones/nueva?cliente_id={loc_id}").get_data(as_text=True)
