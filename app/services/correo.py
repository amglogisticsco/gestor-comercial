"""Borradores y envío de correos. Nada se envía sin una acción explícita (salvo el
envío automático de cumpleaños, que viene desactivado por defecto)."""
import smtplib
import ssl
from collections import defaultdict
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from flask import current_app, render_template

from .. import db
from ..filtros import fecha_larga, moneda
from ..models import Correo, Empresa
from . import pdf


class ErrorEnvio(Exception):
    pass


def _rellenar(texto, **datos):
    return (texto or "").format_map(defaultdict(str, datos))


def firma(empresa):
    if empresa.firma_correo:
        return empresa.firma_correo
    from flask_login import current_user
    autenticado = getattr(current_user, "is_authenticated", False)
    nombre = current_user.nombre if autenticado else ""
    cargo = current_user.cargo if autenticado else ""
    telefono = (current_user.telefono if autenticado else "") or empresa.telefono
    lineas = [nombre, cargo, empresa.nombre, telefono, empresa.email, empresa.web]
    return "\n".join(l for l in lineas if l)


def borrador_cotizacion(cot):
    empresa = Empresa.actual()
    cliente = cot.cliente
    if cot.revision:
        asunto = f"Cotización {cot.numero_base} – Revisión {cot.revision} – {empresa.nombre}"
        intro = (f"Reciba un cordial saludo. Adjuntamos la revisión {cot.revision} de la cotización {cot.numero_base} "
                 f"({cot.numero}), con los ajustes solicitados, correspondiente a ")
    else:
        asunto = f"Cotización {cot.numero} – {empresa.nombre}"
        intro = f"Reciba un cordial saludo. Adjuntamos la cotización {cot.numero} correspondiente a "
    cuerpo = (
        f"Buen día, {cliente.nombre_saludo}:\n\n"
        f"{intro}"
        f"{cot.resumen}, por un valor total de {moneda(cot.total, cot.moneda)}.\n\n"
        f"La oferta tiene una vigencia de {cot.validez_dias} días (hasta el {fecha_larga(cot.vence)}). "
        "Quedamos atentos a sus comentarios o a cualquier ajuste que requiera.\n\n"
        "Cordial saludo,"
    )
    return _crear(cliente, "cotizacion", asunto, cuerpo, "cotizacion", cot.id)


def borrador_anticipo(ant):
    empresa = Empresa.actual()
    cliente = ant.cliente
    referencia = f" (cotización {ant.cotizacion.numero})" if ant.cotizacion else ""
    do = f", D.O. {ant.do_numero}" if ant.do_numero else ""
    limite = f", preferiblemente antes del {fecha_larga(ant.fecha_limite)}" if ant.fecha_limite else ""
    banco = f"\n\nPuede realizar la consignación a:\n{empresa.datos_bancarios}" if empresa.datos_bancarios else ""
    pie = f"\n\n{empresa.pie_anticipo}" if empresa.pie_anticipo else ""
    asunto = f"Solicitud de fondos {ant.numero}{do} – {empresa.nombre}"
    cuerpo = (
        f"Buen día, {cliente.nombre_saludo}:\n\n"
        f"Reciba un cordial saludo. Para dar continuidad a la operación{referencia}{do}, adjuntamos la "
        f"solicitud de fondos {ant.numero} por valor de {moneda(ant.total, 'COP')}{limite}.{banco}{pie}\n\n"
        "Le agradecemos enviarnos el soporte de pago respondiendo a este correo.\n\n"
        "Cordial saludo,"
    )
    return _crear(cliente, "anticipo", asunto, cuerpo, "anticipo", ant.id)


def borrador_cumpleanos(cliente):
    empresa = Empresa.actual()
    datos = {"nombre": cliente.nombre_saludo, "empresa": empresa.nombre, "cliente": cliente.razon_social}
    return _crear(
        cliente, "cumpleanos",
        _rellenar(empresa.cumple_asunto, **datos),
        _rellenar(empresa.cumple_mensaje, **datos),
    )


def borrador_libre_proveedor(proveedor):
    saludo = (proveedor.contacto_nombre or "").split()[0].capitalize() if proveedor.contacto_nombre else ""
    correo = Correo(proveedor=proveedor, tipo="proveedor", para=proveedor.email or "", cc=proveedor.email_cc or "",
                    asunto="", cuerpo=f"Buen día{', ' + saludo if saludo else ''}:\n\n\n\nCordial saludo,")
    db.session.add(correo)
    db.session.commit()
    return correo


def borrador_libre(cliente):
    return _crear(cliente, "libre", "", f"Buen día, {cliente.nombre_saludo}:\n\n\n\nCordial saludo,")


def borrador_solicitud_tarifa(proveedor, cot=None, idioma="es"):
    """Pide tarifa a un proveedor o agente, con los datos de la operación si hay cotización."""
    empresa = Empresa.actual()
    saludo = (proveedor.contacto_nombre or "").split()[0].capitalize() if proveedor.contacto_nombre else ""
    datos = []
    if cot:
        etiquetas_en = {"Origen": "Origin", "Destino": "Destination", "Modalidad": "Mode", "Incoterm": "Incoterm",
                        "Tipo de carga": "Cargo type", "Contenedor": "Equipment", "Peso / Volumen": "Weight / Volume",
                        "Piezas": "Pieces", "Mercancía": "Commodity", "Dimensiones": "Dimensions", "Ruta": "Routing",
                        "Puerto de origen": "Port of loading (POL)", "Puerto de destino": "Port of discharge (POD)",
                        "Aeropuerto de origen": "Airport of departure", "Aeropuerto de destino": "Airport of destination",
                        "Puerto / aeropuerto de origen": "Port / airport of loading",
                        "Puerto / aeropuerto de destino": "Port / airport of discharge"}
        omitir = {"Naviera / Aerolínea", "Tiempo tránsito", "Días libres origen", "Días libres destino"}
        for k, v in cot.datos_servicio:
            if k not in omitir:
                datos.append(f"- {etiquetas_en.get(k, k) if idioma == 'en' else k}: {v}")
        if cot.tipo_operacion and idioma != "en":
            datos.insert(0, f"- Operación: {cot.tipo_operacion}")
    bloque = ("\n".join(datos) + "\n\n") if datos else (
        "- Origen:\n- Destino:\n- Puerto / aeropuerto de origen:\n- Puerto / aeropuerto de destino:\n"
        "- Mercancía:\n- Peso / volumen:\n- Incoterm:\n\n")
    if idioma == "en":
        asunto = "Rate request" + (f" – {cot.origen} to {cot.destino}" if cot and cot.origen and cot.destino else "") + f" – {empresa.nombre}"
        bloque = bloque.replace("- Puerto / aeropuerto de origen:", "- Port / airport of loading:").replace(
            "- Puerto / aeropuerto de destino:", "- Port / airport of discharge:")
        bloque = bloque.replace("- Origen:", "- Origin:").replace("- Destino:", "- Destination:").replace(
            "- Mercancía:", "- Commodity:").replace("- Peso / volumen:", "- Weight / volume:")
        cuerpo = (f"Dear {saludo or 'partner'},\n\nGood day. We kindly request your best rates for the following shipment:\n\n"
                  f"{bloque}Please include validity, transit time, free days and any local charges.\n\n"
                  "Thank you in advance for your prompt reply.\n\nBest regards,")
    else:
        asunto = "Solicitud de tarifa" + (f" – {cot.origen} → {cot.destino}" if cot and cot.origen and cot.destino else "") + f" – {empresa.nombre}"
        cuerpo = (f"Buen día{', ' + saludo if saludo else ''}:\n\nReciba un cordial saludo. Le agradecemos cotizarnos la siguiente operación:\n\n"
                  f"{bloque}Por favor indíquenos vigencia, tiempo de tránsito, días libres y gastos adicionales si aplican.\n\n"
                  "Quedamos atentos.\n\nCordial saludo,")
    correo = Correo(proveedor=proveedor, tipo="proveedor", para=proveedor.email or "", cc=proveedor.email_cc or "",
                    asunto=asunto, cuerpo=cuerpo)
    db.session.add(correo)
    db.session.commit()
    return correo


def _crear(cliente, tipo, asunto, cuerpo, adjunto_tipo=None, adjunto_id=None):
    correo = Correo(
        cliente=cliente, tipo=tipo, para=cliente.email or "", cc=cliente.email_cc or "",
        asunto=asunto, cuerpo=cuerpo, adjunto_tipo=adjunto_tipo, adjunto_id=adjunto_id,
    )
    db.session.add(correo)
    db.session.commit()
    return correo


def _lista(texto):
    return [d.strip() for d in (texto or "").replace(";", ",").split(",") if d.strip()]


def adjunto_pdf(correo):
    doc = correo.adjunto
    if doc is None:
        return None
    contenido = pdf.pdf_cotizacion(doc) if correo.adjunto_tipo == "cotizacion" else pdf.pdf_anticipo(doc)
    return f"{doc.numero}.pdf", contenido


def _responder_a(empresa, remitente):
    """Las respuestas del cliente le llegan al ejecutivo que envió el correo
    (o al correo general de la empresa si el envío fue automático)."""
    from flask_login import current_user

    if getattr(current_user, "is_authenticated", False) and current_user.email:
        return formataddr((current_user.nombre, current_user.email))
    if empresa.email and empresa.email.lower() != remitente.lower():
        return formataddr((empresa.nombre, empresa.email))
    return None


def construir_mensaje(correo):
    cfg = current_app.config
    empresa = Empresa.actual()
    remitente = cfg["SMTP_REMITENTE"] or empresa.email
    if not remitente:
        raise ErrorEnvio("Falta el correo remitente. Configúralo en el archivo .env (SMTP_REMITENTE).")
    destinatarios = _lista(correo.para)
    if not destinatarios:
        raise ErrorEnvio("El correo no tiene destinatario.")
    if not correo.asunto.strip():
        raise ErrorEnvio("El correo no tiene asunto.")

    msg = EmailMessage()
    msg["From"] = formataddr((empresa.nombre, remitente))
    msg["To"] = ", ".join(destinatarios)
    if _lista(correo.cc):
        msg["Cc"] = ", ".join(_lista(correo.cc))
    msg["Subject"] = correo.asunto
    msg["Message-ID"] = make_msgid(domain=remitente.split("@")[-1])
    responder = _responder_a(empresa, remitente)
    if responder:
        msg["Reply-To"] = responder

    texto_firma = firma(empresa)
    msg.set_content(f"{correo.cuerpo}\n\n{texto_firma}")
    msg.add_alternative(
        render_template("email/correo.html", correo=correo, empresa=empresa, firma=texto_firma), subtype="html"
    )
    import mimetypes

    for archivo in correo.archivos:
        if archivo.ruta.exists():
            principal, _, secundario = (archivo.tipo or mimetypes.guess_type(archivo.nombre)[0]
                                        or "application/octet-stream").partition("/")
            msg.add_attachment(archivo.ruta.read_bytes(), maintype=principal, subtype=secundario or "octet-stream",
                               filename=archivo.nombre)
    adjunto = adjunto_pdf(correo)
    if adjunto:
        nombre, contenido = adjunto
        msg.add_attachment(contenido, maintype="application", subtype="pdf", filename=nombre)
    return msg


def enviar(correo):
    """Envía un correo ya revisado. Devuelve True si salió; guarda el error si falla."""
    cfg = current_app.config
    try:
        msg = construir_mensaje(correo)
        copia_oculta = _lista(cfg["SMTP_COPIA_OCULTA"])
        if cfg["SMTP_MODO"] == "smtp":
            if not cfg["SMTP_HOST"]:
                raise ErrorEnvio("El servidor SMTP no está configurado (archivo .env).")
            _enviar_smtp(msg, copia_oculta)
        else:
            bandeja = Path(cfg["BANDEJA_PRUEBA"])
            bandeja.mkdir(parents=True, exist_ok=True)
            (bandeja / f"{datetime.now():%Y%m%d-%H%M%S}-{correo.id}.eml").write_bytes(bytes(msg))
    except (ErrorEnvio, smtplib.SMTPException, OSError) as exc:
        correo.estado = "error"
        correo.error = str(exc)
        db.session.commit()
        return False

    correo.estado = "enviado"
    correo.error = ""
    correo.enviado_en = datetime.now()
    _actualizar_documento(correo)
    db.session.commit()
    return True


def _enviar_smtp(msg, copia_oculta):
    cfg = current_app.config
    contexto = ssl.create_default_context()
    if cfg["SMTP_SEGURIDAD"] == "ssl":
        servidor = smtplib.SMTP_SSL(cfg["SMTP_HOST"], cfg["SMTP_PORT"], context=contexto, timeout=30)
    else:
        servidor = smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=30)
    with servidor:
        if cfg["SMTP_SEGURIDAD"] == "tls":
            servidor.starttls(context=contexto)
        if cfg["SMTP_USUARIO"]:
            servidor.login(cfg["SMTP_USUARIO"], cfg["SMTP_CLAVE"])
        destinos = _lista(msg["To"]) + _lista(msg.get("Cc", "")) + copia_oculta
        servidor.send_message(msg, to_addrs=destinos)


def _actualizar_documento(correo):
    doc = correo.adjunto
    if correo.adjunto_tipo == "cotizacion" and doc and doc.estado == "borrador":
        doc.estado = "enviada"
    if correo.adjunto_tipo == "anticipo" and doc and doc.estado == "pendiente":
        doc.estado = "enviada"
