"""DO (documento de operación): consecutivo DO-AAAA-0001 para identificar cada proceso y su carpeta."""
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_

from .. import db
from ..models import ESTADOS_DO, MODALIDADES, TIPOS_OPERACION, Cliente, Cotizacion, Operacion, numero_do
from . import a_fecha, obtener

bp = Blueprint("operaciones", __name__, url_prefix="/do")

CAMPOS_TEXTO = ["tipo_operacion", "modalidad", "origen", "destino", "mercancia", "transportista", "doc_transporte",
                "contenedores", "referencia_cliente", "responsable", "notas"]


@bp.route("/")
def lista():
    q = request.args.get("q", "").strip()
    estado = request.args.get("estado", "")
    tipo = request.args.get("tipo", "")
    consulta = Operacion.query.join(Cliente)
    if q:
        patron = f"%{q}%"
        consulta = consulta.filter(or_(Operacion.numero.ilike(patron), Cliente.razon_social.ilike(patron),
                                       Operacion.doc_transporte.ilike(patron), Operacion.origen.ilike(patron),
                                       Operacion.destino.ilike(patron), Operacion.mercancia.ilike(patron),
                                       Operacion.referencia_cliente.ilike(patron),
                                       Operacion.contenedores.ilike(patron)))
    if tipo:
        consulta = consulta.filter(Operacion.tipo_operacion == tipo)
    todas = consulta.order_by(Operacion.id.desc()).all()
    conteo = {k: sum(1 for o in todas if o.estado == k) for k in ESTADOS_DO}
    if estado:
        todas = [o for o in todas if o.estado == estado]
    tipos_usados = [t for (t,) in db.session.query(Operacion.tipo_operacion).distinct() if t]
    return render_template("operaciones/lista.html", operaciones=todas, q=q, estado=estado, tipo=tipo,
                           estados=ESTADOS_DO, conteo=conteo, tipos=tipos_usados)


def _desde_cotizacion(do, cot):
    do.cotizacion_id, do.cliente_id = cot.id, cot.cliente_id
    do.tipo_operacion = cot.tipo_operacion or "Importación"
    do.modalidad = cot.modalidad
    do.origen, do.destino = cot.origen, cot.destino
    do.mercancia = cot.mercancia
    do.transportista = cot.transportista
    do.contenedores = cot.contenedor if cot.contenedor and cot.contenedor != "No aplica" else ""


def _guardar(do):
    cot = db.session.get(Cotizacion, request.form.get("cotizacion_id", type=int) or 0)
    do.cotizacion_id = cot.id if cot else None
    do.cliente_id = cot.cliente_id if cot else request.form.get("cliente_id", type=int)
    if not do.cliente_id or not db.session.get(Cliente, do.cliente_id):
        flash("Selecciona el cliente del DO.", "error")
        return False
    for campo in CAMPOS_TEXTO:
        setattr(do, campo, request.form.get(campo, "").strip())
    do.fecha_apertura = a_fecha(request.form.get("fecha_apertura")) or date.today()
    do.eta = a_fecha(request.form.get("eta"))
    return True


def _contexto(do):
    return {
        "do": do, "tipos": TIPOS_OPERACION, "modalidades": MODALIDADES,
        "clientes": Cliente.query.filter_by(activo=True).order_by(Cliente.razon_social).all(),
        "cotizaciones": Cotizacion.query.filter(Cotizacion.estado.notin_(["rechazada", "reemplazada"]))
        .order_by(Cotizacion.id.desc()).all(),
    }


@bp.route("/nuevo", methods=["GET", "POST"])
def nuevo():
    do = Operacion(fecha_apertura=date.today(), tipo_operacion="Importación", responsable=current_user.nombre,
                   cliente_id=request.args.get("cliente_id", type=int))
    cot = db.session.get(Cotizacion, request.args.get("cotizacion_id", type=int) or 0)
    if cot and request.method == "GET":
        _desde_cotizacion(do, cot)
    if request.method == "POST":
        if _guardar(do):
            do.numero = numero_do()
            db.session.add(do)
            db.session.commit()
            flash(f"{do.numero} abierto. Nombre de la carpeta: {do.carpeta}", "ok")
            return redirect(url_for("operaciones.ver", ident=do.id))
        db.session.expunge_all()
    return render_template("operaciones/form.html", **_contexto(do))


@bp.route("/desde-cotizacion/<int:ident>", methods=["POST"])
def desde_cotizacion(ident):
    """Abre el DO directamente desde una cotización aceptada."""
    cot = obtener(Cotizacion, ident)
    do = Operacion(fecha_apertura=date.today(), responsable=current_user.nombre)
    _desde_cotizacion(do, cot)
    do.numero = numero_do()
    db.session.add(do)
    db.session.commit()
    flash(f"{do.numero} abierto. Nombre de la carpeta: {do.carpeta}", "ok")
    return redirect(url_for("operaciones.ver", ident=do.id))


@bp.route("/<int:ident>/editar", methods=["GET", "POST"])
def editar(ident):
    do = obtener(Operacion, ident)
    if request.method == "POST":
        if _guardar(do):
            for a in do.anticipos:  # mantiene el número visible en las solicitudes de fondos
                a.do_numero = do.numero
            db.session.commit()
            flash(f"{do.numero} actualizado.", "ok")
            return redirect(url_for("operaciones.ver", ident=do.id))
        db.session.rollback()
    return render_template("operaciones/form.html", **_contexto(do))


@bp.route("/<int:ident>")
def ver(ident):
    return render_template("operaciones/ver.html", do=obtener(Operacion, ident), estados=ESTADOS_DO)


@bp.route("/<int:ident>/estado", methods=["POST"])
def cambiar_estado(ident):
    do = obtener(Operacion, ident)
    estado = request.form.get("estado")
    if estado in ESTADOS_DO:
        do.estado = estado
        do.fecha_cierre = date.today() if estado == "cerrado" else None
        db.session.commit()
        flash(f"{do.numero}: {ESTADOS_DO[estado].lower()}.", "ok")
    return redirect(url_for("operaciones.ver", ident=do.id))


@bp.route("/<int:ident>/eliminar", methods=["POST"])
def eliminar(ident):
    """Solo administradores. Las solicitudes de fondos se conservan, sin DO asignado."""
    if not current_user.es_admin:
        abort(403)
    do = obtener(Operacion, ident)
    if request.form.get("confirmar") != "ELIMINAR":
        return redirect(url_for("operaciones.ver", ident=do.id))
    numero = do.numero
    for a in do.anticipos:
        a.do_id = None
    db.session.delete(do)
    db.session.commit()
    flash(f"{numero} eliminado. Ojo: ese número no se vuelve a usar si ya hay DO posteriores.", "ok")
    return redirect(url_for("operaciones.lista"))
