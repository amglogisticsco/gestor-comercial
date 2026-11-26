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
    assert "Cliente CLI-0001 creado" in r.get_data(as_text=True)
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


def test_importar_excel_y_tarifas(cliente_http):
    from pathlib import Path
    from app.models import Cotizacion, Tarifa, numero_cotizacion
    c = cliente_http
    post(c, "/setup", {"empresa": "AMG LOGISTICS SAS", "nombre": "David", "email": "d@amg.test", "clave": "clave-segura"})
    libro = Path(__file__).parent / "datos" / "libro_prueba.xlsx"
    datos = {"_csrf": csrf(c, "/configuracion/importar"), "cotizaciones": "1",
             "archivo": (libro.open("rb"), "libro.xlsx")}
    r = c.post("/configuracion/importar", data=datos, content_type="multipart/form-data", follow_redirects=True)
    texto = r.get_data(as_text=True)
    assert "2 clientes" in texto and "2 tarifas" in texto and "1 cotizaciones" in texto, texto[:400]
    with c.app.app_context():
        assert Cliente.query.filter_by(razon_social="AMG LOGISTICS SAS").count() == 0  # la empresa no es cliente
        caribe = Cliente.query.filter_by(codigo="CLI-0003").one()
        assert caribe.es_exterior
        assert {t.codigo: t.estado for t in Tarifa.query} == {"TAR-0001": "vigente", "TAR-0002": "vencida"}
        cot = Cotizacion.query.filter_by(numero="COT-0007").one()
        assert cot.estado == "aprobada" and cot.total == 2699 and cot.iva_pct == 0
        assert numero_cotizacion() == "COT-0008"  # la numeración continúa
    # Reimportar no duplica
    datos["archivo"] = (libro.open("rb"), "libro.xlsx")
    datos["_csrf"] = csrf(c, "/configuracion/importar")
    c.post("/configuracion/importar", data=datos, content_type="multipart/form-data")
    with c.app.app_context():
        assert Cliente.query.count() == 2 and Tarifa.query.count() == 2
    for url in ["/tarifas/", "/tarifas/?estado=vencida", "/tarifas/nueva", "/tarifas/1", "/cotizaciones/nueva", "/servicios/", "/"]:
        assert c.get(url).status_code == 200, url


def test_tarifas_por_cliente_y_proceso(cliente_http):
    from app.models import Servicio, Tarifa, buscar_tarifa
    c = cliente_http
    with c.app.app_context():
        ag = Servicio.query.filter_by(codigo="SER-005").one()  # Agenciamiento aduanero
        a = Cliente(razon_social="Cliente A"); b = Cliente(razon_social="Cliente B")
        db.session.add_all([a, b]); db.session.flush()
        general = Tarifa(codigo="T-GEN", servicio=ag, valor=450, moneda="USD")
        especial = Tarifa(codigo="T-A-EXPO", servicio=ag, valor=380, moneda="USD", cliente_id=a.id, proceso="Exportación")
        impo = Tarifa(codigo="T-IMPO", servicio=ag, valor=600, moneda="USD", proceso="Importación")
        db.session.add_all([general, especial, impo]); db.session.commit()
        # Cliente A exportando: su tarifa especial
        assert buscar_tarifa(ag.id, cliente_id=a.id, proceso="Exportación").codigo == "T-A-EXPO"
        # Cliente B nunca recibe la tarifa especial de A
        assert buscar_tarifa(ag.id, cliente_id=b.id, proceso="Exportación").codigo == "T-GEN"
        # Importación: la tarifa del proceso
        assert buscar_tarifa(ag.id, cliente_id=b.id, proceso="Importación").codigo == "T-IMPO"
        # Cliente A importando: no aplica su tarifa de exportación
        assert buscar_tarifa(ag.id, cliente_id=a.id, proceso="Importación").codigo == "T-IMPO"


def test_directorio_proveedores_y_agentes(cliente_http):
    from app.models import Correo, Proveedor, Servicio, Tarifa
    c = cliente_http
    post(c, "/setup", {"empresa": "AMG LOGISTICS SAS", "nombre": "David", "email": "d@amg.test", "clave": "clave-segura"})
    # Agente internacional
    r = post(c, "/directorio/proveedores/nuevo", {"nombre": "Shanghai Freight Co", "tipo": "Agente internacional",
                                                 "email": "pricing@sfc.test", "pais": "China", "red": "WCA",
                                                 "cobertura": "Shanghái, Ningbo", "servicios_ofrecidos": "FCL, LCL"})
    assert "PRV-0001" in r.get_data(as_text=True)
    with c.app.app_context():
        flete = Servicio.query.filter_by(codigo="SER-001").one().id
        cargue = Servicio.query.filter_by(codigo="SER-009").one().id
        cliente = Cliente(razon_social="MODALUX INC", pais="Panamá"); db.session.add(cliente); db.session.commit()
        cid = cliente.id
    # Tarifas con proveedor nuevo creado desde el formulario
    post(c, "/tarifas/nueva", {"servicio_id": flete, "proveedor_id": "nuevo", "nuevo_proveedor": "MAERSK",
                               "nuevo_tipo": "Naviera", "origen": "CARTAGENA", "destino": "PANAMA", "moneda": "USD",
                               "valor": "1450", "activo": "1"})
    post(c, "/tarifas/nueva", {"servicio_id": cargue, "proveedor_id": "nuevo", "nuevo_proveedor": "Auxiliares de Cargue",
                               "nuevo_tipo": "Otro", "origen": "CARTAGENA", "destino": "PANAMA", "moneda": "USD",
                               "valor": "270", "activo": "1"})
    with c.app.app_context():
        maersk = Proveedor.query.filter_by(nombre="MAERSK").one()
        assert maersk.tipo == "Naviera" and maersk.tarifas[0].es_transportista
        aux = Proveedor.query.filter_by(nombre="Auxiliares de Cargue").one()
        assert not aux.tarifas[0].es_transportista
        t_flete, t_cargue = maersk.tarifas[0].id, aux.tarifas[0].id
        agente_id = Proveedor.query.filter_by(nombre="Shanghai Freight Co").one().id
    # Búsqueda única en el directorio
    texto = c.get("/directorio/?q=shanghai").get_data(as_text=True)
    assert "Shanghai Freight Co" in texto and "MODALUX" not in texto
    assert "MODALUX INC" in c.get("/directorio/?q=modalux").get_data(as_text=True)
    # Cotización: la naviera es la visible; el proveedor del cargue no sale en el PDF
    r = post(c, "/cotizaciones/nueva", {"cliente_id": cid, "moneda": "USD", "iva_pct": "0", "tarifa_id": t_flete,
                                       "transportista": "MAERSK", "origen": "CARTAGENA", "destino": "PANAMA", "modalidad": "Marítimo",
                                       "puerto_origen": "Puerto de Cartagena (COCTG)", "puerto_destino": "Puerto de Colón / Manzanillo – Panamá (PAMIT)",
                                       "item_descripcion": ["Flete marítimo", "Cargue y descargue"], "item_cantidad": ["1", "1"],
                                       "item_unidad": ["Contenedor", "Servicio"], "item_precio": ["1450", "270"],
                                       "item_iva": ["0", "0"], "item_servicio": [str(flete), str(cargue)],
                                       "item_tarifa": [str(t_flete), str(t_cargue)], "item_obs": ["", ""]})
    with c.app.app_context():
        cot = Cotizacion.query.one()
        from app.services.pdf import pdf_cotizacion
        from flask import render_template
        from app.models import Empresa
        html = render_template("pdf/cotizacion.html", c=cot, empresa=Empresa.actual(), logo=None)
        assert "MAERSK" in html and "Auxiliares de Cargue" not in html
        assert "Puerto de origen" in html and "COCTG" in html
        cot_id = cot.id
    # Pedir cotización al agente, en inglés, con los datos de la operación
    r = post(c, f"/directorio/proveedores/{agente_id}/pedir-cotizacion", {"cotizacion_id": cot_id, "idioma": "en"},
             desde=f"/directorio/proveedores/{agente_id}")
    assert "Revisar y enviar" in r.get_data(as_text=True)
    with c.app.app_context():
        m = Correo.query.filter_by(tipo="proveedor").one()
        assert m.para == "pricing@sfc.test" and m.estado == "borrador"
        assert "Rate request" in m.asunto and "CARTAGENA" in m.cuerpo
        assert "Port of loading (POL): Puerto de Cartagena (COCTG)" in m.cuerpo
        assert "Port of discharge (POD): Puerto de Colón" in m.cuerpo
    for url in ["/directorio/", "/directorio/?ver=agentes", "/directorio/?ver=proveedores&tipo=Naviera",
                f"/directorio/proveedores/{agente_id}", f"/directorio/proveedores/{agente_id}/editar",
                "/directorio/proveedores/nuevo?agente=1", "/tarifas/nueva", f"/cotizaciones/{cot_id}/editar", "/correos/"]:
        assert c.get(url).status_code == 200, url


def test_eliminar_definitivo_y_reactivar(cliente_http):
    from app.models import Anticipo, Correo, Cotizacion, ItemCotizacion, Usuario
    c = cliente_http
    post(c, "/setup", {"empresa": "AMG", "nombre": "David", "email": "d@amg.test", "clave": "clave-segura"})
    with c.app.app_context():
        cli = Cliente(razon_social="Cliente de prueba", email="x@test.co")
        db.session.add(cli); db.session.flush()
        cot = Cotizacion(numero="COT-0001", cliente=cli, estado="enviada")
        cot.items = [ItemCotizacion(descripcion="Flete", precio=100)]
        db.session.add(cot); db.session.flush()
        db.session.add(Anticipo(numero="SF-2026-0001", cliente=cli, cotizacion=cot, monto=50, estado="enviada"))
        db.session.add(Correo(cliente=cli, tipo="cotizacion", adjunto_tipo="cotizacion", adjunto_id=cot.id, estado="enviado"))
        u = Usuario(nombre="Laura", email="l@amg.test", rol="usuario"); u.set_password("clave-laura")
        db.session.add(u); db.session.commit()
        cid = cli.id
    # Sin confirmación: solo inactiva
    post(c, f"/clientes/{cid}/eliminar", {}, desde=f"/clientes/{cid}")
    with c.app.app_context():
        assert db.session.get(Cliente, cid).activo is False
    # Reactivar desde el formulario de edición
    post(c, f"/clientes/{cid}/editar", {"razon_social": "Cliente de prueba", "activo": "1"})
    with c.app.app_context():
        assert db.session.get(Cliente, cid).activo is True
    # Un usuario normal no puede borrar definitivamente
    post(c, "/logout", {}, desde="/")
    post(c, "/login", {"email": "l@amg.test", "clave": "clave-laura"})
    datos = {"confirmar": "ELIMINAR", "_csrf": csrf(c, f"/clientes/{cid}")}
    assert c.post(f"/clientes/{cid}/eliminar", data=datos).status_code == 403
    # El administrador sí, y se borra todo lo relacionado
    post(c, "/logout", {}, desde="/")
    post(c, "/login", {"email": "d@amg.test", "clave": "clave-segura"})
    r = post(c, f"/clientes/{cid}/eliminar", {"confirmar": "ELIMINAR"}, desde=f"/clientes/{cid}")
    assert "eliminado definitivamente" in r.get_data(as_text=True)
    with c.app.app_context():
        assert db.session.get(Cliente, cid) is None
        assert Cotizacion.query.count() == Anticipo.query.count() == Correo.query.count() == 0


def test_servicios_duplicados_eliminar_y_fusionar(cliente_http):
    from app.models import ItemCotizacion, Servicio, Tarifa
    c = cliente_http
    post(c, "/setup", {"empresa": "AMG", "nombre": "David", "email": "d@amg.test", "clave": "clave-segura"})
    with c.app.app_context():
        original = Servicio.query.filter_by(codigo="SER-002").one()  # Flete aéreo
        dup = Servicio(nombre="FLETE AEREO", unidad="Kg"); suelto = Servicio(nombre="Servicio sin uso")
        db.session.add_all([dup, suelto]); db.session.flush()
        db.session.add(Tarifa(servicio_id=dup.id, valor=6, moneda="USD"))
        cli = Cliente(razon_social="X"); db.session.add(cli); db.session.flush()
        cot = Cotizacion(numero="COT-0009", cliente=cli)
        cot.items = [ItemCotizacion(descripcion="Flete", servicio_id=dup.id, precio=6)]
        db.session.add(cot); db.session.commit()
        ids = (original.id, dup.id, suelto.id)
    texto = c.get("/servicios/").get_data(as_text=True)
    assert "Posible duplicado" in texto
    # Sin uso: se elimina directo
    post(c, f"/servicios/{ids[2]}/eliminar", {}, desde="/servicios/")
    # En uso sin destino: no se borra
    r = post(c, f"/servicios/{ids[1]}/eliminar", {}, desde="/servicios/")
    assert "Fusiónalo" in r.get_data(as_text=True)
    # Fusionar: tarifas e ítems pasan al original
    post(c, f"/servicios/{ids[1]}/eliminar", {"destino_id": ids[0]}, desde="/servicios/")
    with c.app.app_context():
        assert db.session.get(Servicio, ids[1]) is None and db.session.get(Servicio, ids[2]) is None
        assert Tarifa.query.one().servicio_id == ids[0]
        assert ItemCotizacion.query.one().servicio_id == ids[0]
    # Un reinicio no vuelve a crear servicios borrados del catálogo inicial
    with c.app.app_context():
        from app.models import sembrar_datos
        db.session.delete(db.session.get(Servicio, ids[0])); db.session.commit()
        Tarifa.query.delete(); ItemCotizacion.query.delete(); db.session.commit()
        sembrar_datos()
        assert Servicio.query.filter_by(codigo="SER-002").count() == 0


def test_revisiones_de_cotizacion(cliente_http):
    from app.models import ItemCotizacion
    c = cliente_http
    post(c, "/setup", {"empresa": "AMG", "nombre": "David", "email": "d@amg.test", "clave": "clave-segura"})
    with c.app.app_context():
        cli = Cliente(razon_social="MODALUX", email="m@x.co"); db.session.add(cli); db.session.flush()
        cot = Cotizacion(numero="COT-0005", cliente=cli, estado="enviada", moneda="USD", origen="CARTAGENA")
        cot.items = [ItemCotizacion(descripcion="Flete", precio=1450)]
        db.session.add(cot); db.session.commit(); cid = cot.id
    # Un borrador no se revisa
    r = post(c, f"/cotizaciones/{cid}/revision", {}, desde=f"/cotizaciones/{cid}")
    assert "revisión COT-0005-R1" in r.get_data(as_text=True)
    with c.app.app_context():
        orig = db.session.get(Cotizacion, cid); r1 = Cotizacion.query.filter_by(numero="COT-0005-R1").one()
        assert orig.estado == "reemplazada" and orig.reemplazada_por_id == r1.id
        assert r1.revision == 1 and r1.estado == "borrador" and r1.items[0].precio == 1450
        assert [v.numero for v in r1.versiones] == ["COT-0005", "COT-0005-R1"]
        r1_id = r1.id
        from app.services import correo as sc
        assert "Revisión 1" in sc.borrador_cotizacion(r1).asunto
        from app.models import numero_cotizacion
        assert numero_cotizacion() == "COT-0006"  # las revisiones no consumen numeración
    # La versión reemplazada no permite cambiar estado
    post(c, f"/cotizaciones/{cid}/estado", {"estado": "aprobada"}, desde=f"/cotizaciones/{cid}")
    with c.app.app_context():
        assert db.session.get(Cotizacion, cid).estado == "reemplazada"
        db.session.get(Cotizacion, r1_id).estado = "enviada"; db.session.commit()
    # R2 a partir de R1
    post(c, f"/cotizaciones/{r1_id}/revision", {}, desde=f"/cotizaciones/{r1_id}")
    with c.app.app_context():
        r2 = Cotizacion.query.filter_by(numero="COT-0005-R2").one(); r2_id = r2.id
    assert "Versiones" in c.get(f"/cotizaciones/{r2_id}").get_data(as_text=True)
    assert c.get(f"/cotizaciones/{r2_id}/pdf").data[:4] == b"%PDF"
    # Borrar R2 (borrador) reabre R1
    post(c, f"/cotizaciones/{r2_id}/eliminar", {}, desde=f"/cotizaciones/{r2_id}")
    with c.app.app_context():
        assert db.session.get(Cotizacion, r1_id).estado == "enviada"


def test_adjuntar_archivos_a_correos(cliente_http):
    import io
    from app.models import ArchivoCorreo, Correo, Proveedor
    c = cliente_http
    post(c, "/setup", {"empresa": "AMG", "nombre": "David", "email": "d@amg.test", "clave": "clave-segura"})
    with c.app.app_context():
        p = Proveedor(nombre="Agente Shanghai", tipo="Agente internacional", email="pricing@sh.test")
        db.session.add(p); db.session.commit(); pid = p.id
    # Correo libre a un proveedor/agente
    r = post(c, f"/correos/nuevo-proveedor/{pid}", {}, desde=f"/directorio/proveedores/{pid}")
    assert "Revisar y enviar" in r.get_data(as_text=True)
    with c.app.app_context():
        mid = Correo.query.one().id
    datos = {"_csrf": csrf(c, f"/correos/{mid}"), "para": "pricing@sh.test", "asunto": "Documentos embarque",
             "cuerpo": "Adjunto BL", "accion": "adjuntar",
             "archivos": [(io.BytesIO(b"%PDF-1.4 prueba"), "BL MSCU123.pdf"), (io.BytesIO(b"x"), "virus.exe")]}
    r = c.post(f"/correos/{mid}", data=datos, content_type="multipart/form-data", follow_redirects=True)
    texto = r.get_data(as_text=True)
    assert "1 archivo adjuntado" in texto and "no se adjuntó" in texto and "BL MSCU123.pdf" in texto
    with c.app.app_context():
        a = ArchivoCorreo.query.one(); aid, ruta = a.id, a.ruta
        assert ruta.exists() and Correo.query.one().asunto == "Documentos embarque"
    # Descargar
    assert c.get(f"/correos/{mid}/archivos/{aid}").data == b"%PDF-1.4 prueba"
    # Enviar: el archivo viaja en el correo
    r = post(c, f"/correos/{mid}", {"para": "pricing@sh.test", "asunto": "Documentos embarque", "cuerpo": "Adjunto BL",
                                    "accion": "enviar"})
    from email import message_from_bytes, policy
    eml = list(c.bandeja.glob("*.eml"))[0]
    msg = message_from_bytes(eml.read_bytes(), policy=policy.default)
    assert [x.get_filename() for x in msg.iter_attachments()] == ["BL MSCU123.pdf"]
    assert "BL MSCU123.pdf" in c.get(f"/correos/{mid}").get_data(as_text=True)  # registro en enviados
    # Quitar un adjunto de un borrador y borrar el archivo del disco
    r = post(c, f"/correos/nuevo-proveedor/{pid}", {}, desde=f"/directorio/proveedores/{pid}")
    with c.app.app_context():
        mid2 = Correo.query.order_by(Correo.id.desc()).first().id
    datos = {"_csrf": csrf(c, f"/correos/{mid2}"), "accion": "adjuntar", "archivos": [(io.BytesIO(b"abc"), "lista.xlsx")]}
    c.post(f"/correos/{mid2}", data=datos, content_type="multipart/form-data")
    with c.app.app_context():
        a2 = ArchivoCorreo.query.filter_by(correo_id=mid2).one(); a2id, ruta2 = a2.id, a2.ruta
    post(c, f"/correos/{mid2}/archivos/{a2id}/quitar", {}, desde=f"/correos/{mid2}")
    with c.app.app_context():
        assert ArchivoCorreo.query.filter_by(correo_id=mid2).count() == 0
    assert not ruta2.exists()


def test_actualizar_tarifa_con_historial(cliente_http):
    from app.models import HistorialTarifa, ItemCotizacion, Servicio, Tarifa
    c = cliente_http
    post(c, "/setup", {"empresa": "AMG", "nombre": "David", "email": "d@amg.test", "clave": "clave-segura"})
    with c.app.app_context():
        s = Servicio.query.filter_by(codigo="SER-001").one()
        t = Tarifa(codigo="TAR-0001", servicio=s, valor=1450, moneda="USD", activo=True)
        cli = Cliente(razon_social="X"); db.session.add_all([t, cli]); db.session.flush()
        cot = Cotizacion(numero="COT-0001", cliente=cli)
        cot.items = [ItemCotizacion(descripcion="Flete", precio=1450, tarifa_id=t.id)]
        db.session.add(cot); db.session.commit(); tid = t.id
    r = post(c, f"/tarifas/{tid}/actualizar", {"valor": "1.390", "moneda": "USD", "vigencia_hasta": "2026-12-31"},
             desde="/tarifas/")
    assert "1.390" in r.get_data(as_text=True)
    with c.app.app_context():
        t = db.session.get(Tarifa, tid)
        assert t.valor == 1390 and len(t.historial) == 1
        h = t.historial[0]
        assert h.valor_anterior == 1450 and h.valor_nuevo == 1390 and h.usuario == "David"
        assert Cotizacion.query.one().items[0].precio == 1450  # las cotizaciones hechas no cambian
    assert "Historial de cambios" in c.get(f"/tarifas/{tid}").get_data(as_text=True)
    assert "Actualizar" in c.get("/tarifas/").get_data(as_text=True)
