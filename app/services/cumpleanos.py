from datetime import date

from flask import current_app

from .. import db
from ..models import Cliente, Correo, Empresa
from . import correo as servicio_correo


def con_fecha():
    return Cliente.query.filter(Cliente.activo.is_(True), Cliente.fecha_nacimiento.isnot(None)).all()


def cumplen_hoy(hoy=None):
    hoy = hoy or date.today()
    return [c for c in con_fecha() if c.cumple_en(hoy.year) == hoy]


def proximos(dias=30, hoy=None):
    hoy = hoy or date.today()
    lista = [c for c in con_fecha() if c.dias_para_cumple(hoy) is not None and c.dias_para_cumple(hoy) <= dias]
    return sorted(lista, key=lambda c: c.dias_para_cumple(hoy))


def ya_preparado(cliente, anio):
    return any(
        c.tipo == "cumpleanos" and c.creado.year == anio
        for c in Correo.query.filter_by(cliente_id=cliente.id, tipo="cumpleanos").all()
    )


def preparar_saludos(hoy=None):
    """Crea el borrador de saludo para quien cumple hoy (una vez por año).
    Solo envía si el envío automático está activado en Configuración."""
    hoy = hoy or date.today()
    empresa = Empresa.actual()
    creados = []
    for cliente in cumplen_hoy(hoy):
        if not cliente.email or ya_preparado(cliente, hoy.year):
            continue
        borrador = servicio_correo.borrador_cumpleanos(cliente)
        creados.append(borrador)
        if empresa.cumple_auto_envio:
            servicio_correo.enviar(borrador)
    if creados:
        current_app.logger.info("Saludos de cumpleaños preparados: %s", len(creados))
    db.session.commit()
    return creados
