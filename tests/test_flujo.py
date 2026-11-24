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
    adjuntos = [p.get_filename() for p in msg.iter_attachments()]
    assert adjuntos == [f"{cot.numero}.pdf"]
    with c.app.app_context():
        assert db.session.get(Cotizacion, cot_id).estado == "enviada"

    # Aprobada → anticipo del 50 %
    post(c, f"/cotizaciones/{cot_id}/estado", {"estado": "aprobada"}, desde=f"/cotizaciones/{cot_id}")
    r = post(c, f"/anticipos/nuevo?cotizacion_id={cot_id}", {
        "cotizacion_id": cot_id, "porcentaje": "50", "monto": "", "fecha": hoy.isoformat(),
        "fecha_limite": hoy.isoformat(), "concepto": "Anticipo", "notas": "",
    })
    assert "ANT-" in r.get_data(as_text=True)
    with c.app.app_context():
        ant = Anticipo.query.one()
        assert ant.monto == 4_892_500
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
                "/anticipos/nuevo", "/correos/", "/correos/?vista=enviados", f"/correos/{bid}", "/configuracion/"]:
        assert c.get(url).status_code == 200, url


def test_cumple_29_febrero():
    cliente = Cliente(razon_social="X", fecha_nacimiento=date(1992, 2, 29))
    assert cliente.cumple_en(2027) == date(2027, 2, 28)
    assert cliente.cumple_en(2028) == date(2028, 2, 29)
