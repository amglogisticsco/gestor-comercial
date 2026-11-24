from datetime import date, datetime

from flask import abort

from .. import db


def obtener(modelo, ident):
    objeto = db.session.get(modelo, ident)
    if objeto is None:
        abort(404)
    return objeto


def a_fecha(texto):
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date() if texto else None
    except ValueError:
        return None


def a_numero(texto, defecto=0.0):
    if texto is None or str(texto).strip() == "":
        return defecto
    limpio = str(texto).strip().replace(" ", "").replace("$", "")
    # Acepta 1.234.567,89 y 1234567.89
    if "," in limpio:
        limpio = limpio.replace(".", "").replace(",", ".")
    elif limpio.count(".") > 1 or (limpio.count(".") == 1 and len(limpio.split(".")[1]) == 3):
        limpio = limpio.replace(".", "")  # 1.500 = mil quinientos
    try:
        return float(limpio)
    except ValueError:
        return defecto


def hoy():
    return date.today()
