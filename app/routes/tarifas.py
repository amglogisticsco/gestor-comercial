from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import or_

from .. import db
from ..models import ESTADOS_TARIFA, MONEDAS, Servicio, Tarifa, asignar_codigos
from . import a_fecha, a_numero, obtener

bp = Blueprint("tarifas", __name__, url_prefix="/tarifas")


@bp.route("/")
def lista():
    q = request.args.get("q", "").strip()
    estado = request.args.get("estado", "")
    consulta = Tarifa.query.join(Servicio)
    if q:
        patron = f"%{q}%"
        consulta = consulta.filter(or_(Tarifa.codigo.ilike(patron), Tarifa.origen.ilike(patron),
                                       Tarifa.destino.ilike(patron), Tarifa.proveedor.ilike(patron),
                                       Servicio.nombre.ilike(patron), Servicio.codigo.ilike(patron)))
    tarifas = consulta.order_by(Tarifa.codigo).all()
    conteo = {k: sum(1 for t in tarifas if t.estado == k) for k in ESTADOS_TARIFA}
    if estado:
        tarifas = [t for t in tarifas if t.estado == estado]
    return render_template("tarifas/lista.html", tarifas=tarifas, q=q, estado=estado, estados=ESTADOS_TARIFA,
                           conteo=conteo)


@bp.route("/nueva", methods=["GET", "POST"])
@bp.route("/<int:ident>", methods=["GET", "POST"])
def editar(ident=None):
    tarifa = obtener(Tarifa, ident) if ident else Tarifa(activo=True, moneda="USD",
                                                         servicio_id=request.args.get("servicio_id", type=int))
    if request.method == "POST":
        servicio = db.session.get(Servicio, request.form.get("servicio_id", type=int) or 0)
        if servicio is None:
            flash("Selecciona el servicio de la tarifa.", "error")
        else:
            tarifa.servicio = servicio
            for campo in ("origen", "destino", "proveedor", "observaciones"):
                setattr(tarifa, campo, request.form.get(campo, "").strip())
            tarifa.moneda = request.form.get("moneda") if request.form.get("moneda") in MONEDAS else "USD"
            tarifa.valor = a_numero(request.form.get("valor"))
            tarifa.vigencia_desde = a_fecha(request.form.get("vigencia_desde"))
            tarifa.vigencia_hasta = a_fecha(request.form.get("vigencia_hasta"))
            tarifa.activo = request.form.get("activo", "1") == "1"
            if not tarifa.id:
                db.session.add(tarifa)
            asignar_codigos()
            db.session.commit()
            flash(f"Tarifa {tarifa.codigo} guardada.", "ok")
            return redirect(url_for("tarifas.lista"))
    servicios = Servicio.query.filter_by(activo=True).order_by(Servicio.nombre).all()
    return render_template("tarifas/form.html", t=tarifa, servicios=servicios, monedas=MONEDAS)


@bp.route("/<int:ident>/duplicar", methods=["POST"])
def duplicar(ident):
    t = obtener(Tarifa, ident)
    copia = Tarifa(servicio_id=t.servicio_id, origen=t.origen, destino=t.destino, proveedor=t.proveedor,
                   moneda=t.moneda, valor=t.valor, observaciones=t.observaciones, activo=True)
    db.session.add(copia)
    asignar_codigos()
    db.session.commit()
    flash(f"Se creó {copia.codigo} como copia de {t.codigo}. Actualiza el valor y la vigencia.", "ok")
    return redirect(url_for("tarifas.editar", ident=copia.id))
