from datetime import date

from flask import Blueprint, render_template

from ..models import Anticipo, Correo, Cotizacion
from ..services import cumpleanos

bp = Blueprint("panel", __name__)


@bp.route("/")
def inicio():
    # Respaldo de la tarea diaria: si el servidor estuvo apagado, se preparan al abrir el panel.
    cumpleanos.preparar_saludos()

    hoy = date.today()
    inicio_mes = hoy.replace(day=1)
    cotizaciones = [c for c in Cotizacion.query.order_by(Cotizacion.id.desc()).all() if c.estado != "reemplazada"]
    del_mes = [c for c in cotizaciones if c.fecha >= inicio_mes]
    en_espera = [c for c in cotizaciones if c.estado_actual == "enviada"]
    aprobadas_mes = [c for c in del_mes if c.estado == "aprobada"]
    por_cobrar = Anticipo.query.filter(Anticipo.estado.in_(["pendiente", "enviada"])).order_by(Anticipo.fecha_limite).all()
    borradores = Correo.query.filter(Correo.estado.in_(["borrador", "error"])).order_by(Correo.id.desc()).all()

    return render_template(
        "panel.html",
        kpi={
            "cotizado_mes_usd": sum(c.total for c in del_mes if c.moneda == "USD"),
            "cotizado_mes_cop": sum(c.total for c in del_mes if c.moneda == "COP"),
            "aceptadas": sum(1 for c in cotizaciones if c.estado == "aprobada"),
            "decididas": sum(1 for c in cotizaciones if c.estado != "borrador"),
            "cotizaciones_mes": len(del_mes),
            "aprobadas_mes": len(aprobadas_mes),
            "en_espera": len(en_espera),
            "por_cobrar": sum(a.monto for a in por_cobrar if a.moneda == "COP"),
            "anticipos_pendientes": len(por_cobrar),
        },
        recientes=cotizaciones[:6],
        en_espera=en_espera[:6],
        por_cobrar=por_cobrar[:6],
        borradores=borradores[:6],
        cumples=cumpleanos.proximos(30),
    )
