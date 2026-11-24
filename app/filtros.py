from datetime import date, datetime

from markupsafe import Markup, escape

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
SIMBOLOS = {"COP": "$", "USD": "US$", "EUR": "€"}


def moneda(valor, codigo="COP"):
    valor = valor or 0
    decimales = 0 if codigo == "COP" else 2
    texto = f"{valor:,.{decimales}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{SIMBOLOS.get(codigo, codigo)} {texto}"


def numero(valor):
    if valor is None:
        return ""
    if float(valor).is_integer():
        return f"{int(valor):,}".replace(",", ".")
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def crudo(valor):
    """Número para campos de formulario, sin separadores de miles."""
    if not valor:
        return ""
    return str(int(valor)) if float(valor).is_integer() else f"{valor:.2f}".replace(".", ",")


def fecha(valor):
    if not valor:
        return "—"
    return valor.strftime("%d/%m/%Y")


def fecha_larga(valor):
    if not valor:
        return "—"
    return f"{valor.day} de {MESES[valor.month - 1]} de {valor.year}"


def dia_mes(valor):
    if not valor:
        return "—"
    return f"{valor.day} de {MESES[valor.month - 1]}"


def fecha_hora(valor):
    if not valor:
        return "—"
    return valor.strftime("%d/%m/%Y %H:%M")


def parrafos(texto):
    """Texto plano -> HTML con saltos de línea, escapado."""
    return Markup("<br>".join(escape(linea) for linea in (texto or "").splitlines()))


def registrar(app):
    app.jinja_env.filters.update(
        moneda=moneda, numero=numero, crudo=crudo, fecha=fecha, fecha_larga=fecha_larga,
        dia_mes=dia_mes, fecha_hora=fecha_hora, parrafos=parrafos,
    )
    from .models import ESTADOS_ANTICIPO, ESTADOS_COTIZACION

    estados = {**ESTADOS_COTIZACION, **ESTADOS_ANTICIPO, "enviado": "Enviado", "error": "Error"}
    app.jinja_env.globals.update(hoy=date.today, ahora=datetime.now, ESTADOS=estados)
