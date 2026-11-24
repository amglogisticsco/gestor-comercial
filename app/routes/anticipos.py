from datetime import date, timedelta

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

from .. import db
from ..models import ESTADOS_ANTICIPO, MONEDAS, Anticipo, Cliente, Cotizacion, Empresa, siguiente_numero
from ..services import correo as servicio_correo
from ..services import pdf
from . import a_fecha, a_numero, obtener

bp = Blueprint("anticipos", __name__, url_prefix="/anticipos")


@bp.route("/")
def lista():
    estado = request.args.get("estado", "")
    consulta = Anticipo.query
    if estado:
        consulta = consulta.filter_by(estado=estado)
    return render_template("anticipos/lista.html", anticipos=consulta.order_by(Anticipo.id.desc()).all(),
                           estado=estado, estados=ESTADOS_ANTICIPO)


def _contexto(a):
    return {
        "a": a, "monedas": MONEDAS,
        "clientes": Cliente.query.filter_by(activo=True).order_by(Cliente.razon_social).all(),
        "cotizaciones": Cotizacion.query.filter(Cotizacion.estado != "rechazada").order_by(Cotizacion.id.desc()).all(),
    }


def _guardar(a):
    cotizacion_id = request.form.get("cotizacion_id", type=int)
    cot = db.session.get(Cotizacion, cotizacion_id) if cotizacion_id else None
    a.cotizacion_id = cot.id if cot else None
    a.cliente_id = cot.cliente_id if cot else request.form.get("cliente_id", type=int)
    if not a.cliente_id or not db.session.get(Cliente, a.cliente_id):
        flash("Selecciona un cliente o una cotización.", "error")
        return False
    a.fecha = a_fecha(request.form.get("fecha")) or date.today()
    a.fecha_limite = a_fecha(request.form.get("fecha_limite"))
    a.moneda = cot.moneda if cot else request.form.get("moneda", "COP")
    a.porcentaje = a_numero(request.form.get("porcentaje"), None)
    a.monto = a_numero(request.form.get("monto"))
    if cot and a.porcentaje and not request.form.get("monto"):
        a.monto = round(cot.total * a.porcentaje / 100, 2)
    a.concepto = request.form.get("concepto", "").strip()
    a.notas = request.form.get("notas", "").strip()
    if a.monto <= 0:
        flash("El monto del anticipo debe ser mayor que cero.", "error")
        return False
    return True


@bp.route("/nuevo", methods=["GET", "POST"])
def nuevo():
    empresa = Empresa.actual()
    cot = db.session.get(Cotizacion, request.args.get("cotizacion_id", type=int) or 0)
    a = Anticipo(fecha=date.today(), fecha_limite=date.today() + timedelta(days=5), moneda=empresa.moneda,
                 cliente_id=request.args.get("cliente_id", type=int))
    if cot:
        a.cotizacion_id, a.cliente_id, a.moneda = cot.id, cot.cliente_id, cot.moneda
        a.porcentaje = empresa.anticipo_pct
        a.monto = round(cot.total * empresa.anticipo_pct / 100, 2)
        a.concepto = f"Anticipo para inicio de operación – cotización {cot.numero}"
    if request.method == "POST":
        if _guardar(a):
            a.numero = siguiente_numero(Anticipo, "ANT")
            db.session.add(a)
            db.session.commit()
            flash(f"Solicitud {a.numero} creada.", "ok")
            return redirect(url_for("anticipos.ver", ident=a.id))
        db.session.expunge_all()
    return render_template("anticipos/form.html", **_contexto(a))


@bp.route("/<int:ident>/editar", methods=["GET", "POST"])
def editar(ident):
    a = obtener(Anticipo, ident)
    if request.method == "POST":
        if _guardar(a):
            db.session.commit()
            flash("Solicitud actualizada.", "ok")
            return redirect(url_for("anticipos.ver", ident=a.id))
        db.session.rollback()
    return render_template("anticipos/form.html", **_contexto(a))


@bp.route("/<int:ident>")
def ver(ident):
    return render_template("anticipos/ver.html", a=obtener(Anticipo, ident), estados=ESTADOS_ANTICIPO)


@bp.route("/<int:ident>/pdf")
def ver_pdf(ident):
    a = obtener(Anticipo, ident)
    descarga = "attachment" if request.args.get("descargar") else "inline"
    return Response(pdf.pdf_anticipo(a), mimetype="application/pdf",
                    headers={"Content-Disposition": f'{descarga}; filename="{a.numero}.pdf"'})


@bp.route("/<int:ident>/estado", methods=["POST"])
def cambiar_estado(ident):
    a = obtener(Anticipo, ident)
    estado = request.form.get("estado")
    if estado in ESTADOS_ANTICIPO:
        a.estado = estado
        a.fecha_pago = (a_fecha(request.form.get("fecha_pago")) or date.today()) if estado == "pagada" else None
        db.session.commit()
        flash(f"Estado actualizado a «{ESTADOS_ANTICIPO[estado]}».", "ok")
    return redirect(url_for("anticipos.ver", ident=a.id))


@bp.route("/<int:ident>/correo", methods=["POST"])
def preparar_correo(ident):
    borrador = servicio_correo.borrador_anticipo(obtener(Anticipo, ident))
    return redirect(url_for("correos.editar", ident=borrador.id))
