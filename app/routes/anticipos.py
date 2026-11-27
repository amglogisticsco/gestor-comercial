from datetime import date, timedelta

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user

from .. import db
from ..models import (ESTADOS_ANTICIPO, GRUPOS_ANTICIPO, MODALIDADES, TIPOS_OPERACION, Anticipo, Cliente,
                      Cotizacion, ItemAnticipo, Operacion, Servicio, numero_sf)
from ..services import correo as servicio_correo
from ..services import pdf
from . import a_fecha, a_numero, obtener

bp = Blueprint("anticipos", __name__, url_prefix="/anticipos")

CAMPOS_TEXTO = ["tipo_operacion", "modalidad", "aduana", "origen", "destino", "tipo_mercancia",
                "doc_transporte", "partida_arancelaria", "concepto", "notas"]
CAMPOS_NUMERO = ["trm", "fob", "flete", "seguro", "otros_cif", "arancel_pct", "iva_tributo_pct"]


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
        "a": a, "grupos": GRUPOS_ANTICIPO, "tipos": TIPOS_OPERACION, "modalidades": MODALIDADES,
        "clientes": Cliente.query.filter_by(activo=True).order_by(Cliente.razon_social).all(),
        "cotizaciones": Cotizacion.query.filter(Cotizacion.estado != "rechazada").order_by(Cotizacion.id.desc()).all(),
        "servicios": Servicio.query.filter_by(activo=True).order_by(Servicio.grupo, Servicio.nombre).all(),
        "operaciones": Operacion.query.filter((Operacion.estado.notin_(["cerrado", "anulado"]))
                                             | (Operacion.id == (a.do_id or 0))).order_by(Operacion.id.desc()).all(),
    }


def _guardar(a):
    cotizacion_id = request.form.get("cotizacion_id", type=int)
    cot = db.session.get(Cotizacion, cotizacion_id) if cotizacion_id else None
    do = db.session.get(Operacion, request.form.get("do_id", type=int) or 0)
    a.do_id = do.id if do else None
    if do:
        a.do_numero = do.numero
    elif "do_numero" in request.form:  # número escrito a mano (solicitudes anteriores al módulo de DO)
        a.do_numero = request.form.get("do_numero", "").strip()
    else:
        a.do_numero = ""
    a.cotizacion_id = cot.id if cot else None
    a.cliente_id = cot.cliente_id if cot else (do.cliente_id if do else request.form.get("cliente_id", type=int))
    if not a.cliente_id or not db.session.get(Cliente, a.cliente_id):
        flash("Selecciona un cliente o una cotización.", "error")
        return False
    a.fecha = a_fecha(request.form.get("fecha")) or date.today()
    a.fecha_limite = a_fecha(request.form.get("fecha_limite"))
    a.moneda = request.form.get("moneda") if request.form.get("moneda") in ("COP", "USD") else "COP"
    for campo in CAMPOS_TEXTO:
        setattr(a, campo, request.form.get(campo, "").strip())
    for campo in CAMPOS_NUMERO:
        setattr(a, campo, a_numero(request.form.get(campo), 0))

    grupos = request.form.getlist("item_grupo")
    descripciones = request.form.getlist("item_descripcion")
    valores = request.form.getlist("item_valor")
    a.items = [
        ItemAnticipo(orden=i, grupo=grupos[i] if i < len(grupos) else GRUPOS_ANTICIPO[-1], descripcion=d.strip(),
                     valor=a_numero(valores[i] if i < len(valores) else 0))
        for i, d in enumerate(descripciones) if d.strip()
    ]
    a.monto = a.total
    if a.monto <= 0:
        flash("La solicitud no tiene valor: agrega conceptos o los datos para liquidar tributos.", "error")
        return False
    return True


def _desde_cotizacion(a, cot):
    """Prellena la solicitud con los datos y conceptos de una cotización."""
    a.cotizacion_id, a.cliente_id = cot.id, cot.cliente_id
    a.moneda = cot.moneda if cot.moneda in ("COP", "USD") else "COP"  # misma moneda de la cotización
    a.tipo_operacion = cot.tipo_operacion or "Importación"
    a.modalidad, a.origen, a.destino = cot.modalidad, cot.origen, cot.destino
    a.tipo_mercancia = cot.mercancia
    a.concepto = f"Solicitud de fondos – cotización {cot.numero}"
    grupos = {s.id: s.grupo for s in Servicio.query.all()}
    a.items = []
    for n, i in enumerate(cot.items):
        valor = i.total + i.impuesto(cot.iva_pct)
        item = ItemAnticipo(orden=n, grupo=grupos.get(i.servicio_id, GRUPOS_ANTICIPO[-1]), descripcion=i.descripcion,
                            valor=valor)
        item.valor_origen = valor if cot.moneda != "COP" else 0  # si se pasa a pesos, se convierte con la TRM
        a.items.append(item)


@bp.route("/nuevo", methods=["GET", "POST"])
def nuevo():
    a = Anticipo(fecha=date.today(), fecha_limite=date.today() + timedelta(days=3), moneda="COP",
                 tipo_operacion="Importación", iva_tributo_pct=19, arancel_pct=0,
                 cliente_id=request.args.get("cliente_id", type=int))
    do = db.session.get(Operacion, request.args.get("do_id", type=int) or 0)
    cot = db.session.get(Cotizacion, request.args.get("cotizacion_id", type=int) or 0) or (do.cotizacion if do else None)
    aviso_usd = False
    if cot and request.method == "GET":
        _desde_cotizacion(a, cot)
        aviso_usd = cot.moneda != "COP"  # habilita la conversión a pesos si se cambia la moneda
    if do and request.method == "GET":
        a.do_id, a.do_numero, a.cliente_id = do.id, do.numero, do.cliente_id
        a.tipo_operacion = do.tipo_operacion or a.tipo_operacion
        a.modalidad = do.modalidad or a.modalidad
        a.origen, a.destino = do.origen or a.origen, do.destino or a.destino
        a.tipo_mercancia = do.mercancia or a.tipo_mercancia
        a.doc_transporte = do.doc_transporte
    elif cot and request.method == "GET" and cot.operaciones:
        a.do_id, a.do_numero = cot.operaciones[0].id, cot.operaciones[0].numero
    if request.method == "POST":
        if _guardar(a):
            a.numero = numero_sf()
            db.session.add(a)
            db.session.commit()
            flash(f"Solicitud de fondos {a.numero} creada.", "ok")
            return redirect(url_for("anticipos.ver", ident=a.id))
        db.session.expunge_all()
    return render_template("anticipos/form.html", aviso_usd=aviso_usd, cot_origen=cot, **_contexto(a))


@bp.route("/<int:ident>/editar", methods=["GET", "POST"])
def editar(ident):
    a = obtener(Anticipo, ident)
    if request.method == "POST":
        if _guardar(a):
            db.session.commit()
            flash("Solicitud actualizada.", "ok")
            return redirect(url_for("anticipos.ver", ident=a.id))
        db.session.rollback()
    return render_template("anticipos/form.html", aviso_usd=False, cot_origen=None, **_contexto(a))


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


@bp.route("/<int:ident>/eliminar", methods=["POST"])
def eliminar(ident):
    a = obtener(Anticipo, ident)
    simple = a.estado in ("pendiente", "anulada")
    if not simple and not (current_user.es_admin and request.form.get("confirmar") == "ELIMINAR"):
        flash("Solo un administrador puede eliminar solicitudes enviadas o pagadas.", "error")
        return redirect(url_for("anticipos.ver", ident=a.id))
    from ..services import borrado

    numero = a.numero
    borrado.eliminar_anticipo(a)
    db.session.commit()
    flash(f"Solicitud {numero} eliminada.", "ok")
    return redirect(url_for("anticipos.lista"))
