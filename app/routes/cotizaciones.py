from datetime import date

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user

from .. import db
from ..models import (CONDICIONES_PAGO, CONTENEDORES, ESTADOS_COTIZACION, INCOTERMS, MODALIDADES, MONEDAS,
                      TIPOS_CARGA, TIPOS_OPERACION, TRANSPORTISTAS, Cliente, Cotizacion, Empresa, ItemCotizacion,
                      Servicio, Tarifa, UNIDADES, numero_cotizacion)
from ..services import correo as servicio_correo
from ..services import pdf
from . import a_fecha, a_numero, obtener

bp = Blueprint("cotizaciones", __name__, url_prefix="/cotizaciones")

CAMPOS_TEXTO = ["ejecutivo", "condicion_pago", "tipo_operacion", "modalidad", "incoterm", "origen", "destino", "ruta",
                "mercancia", "tipo_carga", "contenedor", "transportista", "bultos", "peso_kg", "peso_vol",
                "volumen_m3", "dimensiones", "tiempo_transito", "dias_libres_origen", "dias_libres_destino",
                "notas", "condiciones", "nota_tarifas"]


@bp.route("/")
def lista():
    estado = request.args.get("estado", "")
    cotizaciones = Cotizacion.query.order_by(Cotizacion.id.desc()).all()
    if estado:
        cotizaciones = [c for c in cotizaciones if c.estado_actual == estado]
    return render_template("cotizaciones/lista.html", cotizaciones=cotizaciones, estado=estado,
                           estados=ESTADOS_COTIZACION)


def _contexto_form(cot):
    return {
        "c": cot,
        "clientes": Cliente.query.filter_by(activo=True).order_by(Cliente.razon_social).all(),
        "servicios": Servicio.query.filter_by(activo=True).order_by(Servicio.nombre).all(),
        "tarifas": Tarifa.query.filter_by(activo=True).order_by(Tarifa.codigo).all(),
        "unidades": UNIDADES,
        "tipos": TIPOS_OPERACION, "modalidades": MODALIDADES, "incoterms": INCOTERMS, "monedas": MONEDAS,
        "condiciones_pago": CONDICIONES_PAGO, "tipos_carga": TIPOS_CARGA, "contenedores": CONTENEDORES,
        "transportistas": sorted(set(TRANSPORTISTAS) | {t for (t,) in db.session.query(Cotizacion.transportista)
                                                        .distinct() if t}),
    }


def _guardar(cot):
    cliente_id = request.form.get("cliente_id", type=int)
    if not cliente_id or not db.session.get(Cliente, cliente_id):
        flash("Selecciona un cliente.", "error")
        return False
    cot.cliente_id = cliente_id
    cot.fecha = a_fecha(request.form.get("fecha")) or date.today()
    cot.validez_dias = request.form.get("validez_dias", type=int) or 15
    cot.moneda = request.form.get("moneda", "COP")
    cot.iva_pct = a_numero(request.form.get("iva_pct"), 0)
    for campo in CAMPOS_TEXTO:
        setattr(cot, campo, request.form.get(campo, "").strip())
    tarifa_base = db.session.get(Tarifa, request.form.get("tarifa_id", type=int) or 0)
    cot.tarifa_id = tarifa_base.id if tarifa_base else None

    descripciones = request.form.getlist("item_descripcion")
    cantidades = request.form.getlist("item_cantidad")
    unidades = request.form.getlist("item_unidad")
    precios = request.form.getlist("item_precio")
    ivas = request.form.getlist("item_iva")
    servicios = request.form.getlist("item_servicio")
    observaciones = request.form.getlist("item_obs")
    tarifas_item = request.form.getlist("item_tarifa")
    nuevos = []
    for i, descripcion in enumerate(descripciones):
        if not descripcion.strip():
            continue
        nuevos.append(ItemCotizacion(
            orden=i, descripcion=descripcion.strip(),
            cantidad=a_numero(cantidades[i] if i < len(cantidades) else 1, 1),
            unidad=(unidades[i] if i < len(unidades) else "").strip() or "Servicio",
            precio=a_numero(precios[i] if i < len(precios) else 0),
            aplica_iva=(ivas[i] if i < len(ivas) else "0") == "1",
            observacion=(observaciones[i] if i < len(observaciones) else "").strip(),
            servicio_id=int(servicios[i]) if i < len(servicios) and servicios[i].isdigit() else None,
            tarifa_id=int(tarifas_item[i]) if i < len(tarifas_item) and tarifas_item[i].isdigit() else None,
        ))
    if not nuevos:
        flash("Agrega al menos un servicio a la cotización.", "error")
        return False
    cot.items = nuevos
    return True


@bp.route("/nueva", methods=["GET", "POST"])
def nueva():
    empresa = Empresa.actual()
    cot = Cotizacion(cliente_id=request.args.get("cliente_id", type=int), fecha=date.today(),
                     validez_dias=empresa.validez_dias, moneda=empresa.moneda, iva_pct=empresa.iva_pct,
                     condiciones=empresa.condiciones, nota_tarifas=empresa.nota_tarifas, ejecutivo=current_user.nombre)
    cliente = db.session.get(Cliente, cot.cliente_id) if cot.cliente_id else None
    if cliente and cliente.es_exterior:
        cot.iva_pct = 0
    if request.method == "POST":
        if _guardar(cot):
            cot.numero = numero_cotizacion()
            db.session.add(cot)
            db.session.commit()
            flash(f"Cotización {cot.numero} creada.", "ok")
            return redirect(url_for("cotizaciones.ver", ident=cot.id))
        db.session.expunge_all()
    return render_template("cotizaciones/form.html", **_contexto_form(cot))


@bp.route("/<int:ident>/editar", methods=["GET", "POST"])
def editar(ident):
    cot = obtener(Cotizacion, ident)
    if request.method == "POST":
        if _guardar(cot):
            db.session.commit()
            flash("Cotización actualizada.", "ok")
            return redirect(url_for("cotizaciones.ver", ident=cot.id))
        db.session.rollback()
    return render_template("cotizaciones/form.html", **_contexto_form(cot))


@bp.route("/<int:ident>")
def ver(ident):
    return render_template("cotizaciones/ver.html", c=obtener(Cotizacion, ident), estados=ESTADOS_COTIZACION)


@bp.route("/<int:ident>/pdf")
def ver_pdf(ident):
    cot = obtener(Cotizacion, ident)
    descarga = "attachment" if request.args.get("descargar") else "inline"
    return Response(pdf.pdf_cotizacion(cot), mimetype="application/pdf",
                    headers={"Content-Disposition": f'{descarga}; filename="{cot.numero}.pdf"'})


@bp.route("/<int:ident>/estado", methods=["POST"])
def cambiar_estado(ident):
    cot = obtener(Cotizacion, ident)
    estado = request.form.get("estado")
    if estado in ESTADOS_COTIZACION and estado != "vencida":
        cot.estado = estado
        db.session.commit()
        flash(f"Estado actualizado a «{ESTADOS_COTIZACION[estado]}».", "ok")
        if estado == "aprobada" and not cot.anticipos:
            flash("Cotización aprobada. ¿Quieres generar la solicitud de anticipo?", "sugerencia")
    return redirect(url_for("cotizaciones.ver", ident=cot.id))


@bp.route("/<int:ident>/duplicar", methods=["POST"])
def duplicar(ident):
    origen = obtener(Cotizacion, ident)
    copia = Cotizacion(numero=numero_cotizacion(), cliente_id=origen.cliente_id, fecha=date.today(),
                       validez_dias=origen.validez_dias, moneda=origen.moneda, iva_pct=origen.iva_pct)
    for campo in CAMPOS_TEXTO:
        setattr(copia, campo, getattr(origen, campo))
    copia.tarifa_id = origen.tarifa_id
    copia.items = [ItemCotizacion(orden=i.orden, descripcion=i.descripcion, cantidad=i.cantidad, unidad=i.unidad,
                                  precio=i.precio, aplica_iva=i.aplica_iva, servicio_id=i.servicio_id,
                                  observacion=i.observacion, tarifa_id=i.tarifa_id)
                   for i in origen.items]
    db.session.add(copia)
    db.session.commit()
    flash(f"Se creó {copia.numero} a partir de {origen.numero}.", "ok")
    return redirect(url_for("cotizaciones.editar", ident=copia.id))


@bp.route("/<int:ident>/eliminar", methods=["POST"])
def eliminar(ident):
    cot = obtener(Cotizacion, ident)
    if cot.estado != "borrador" or cot.anticipos:
        flash("Solo se pueden eliminar cotizaciones en borrador y sin anticipos.", "error")
        return redirect(url_for("cotizaciones.ver", ident=cot.id))
    db.session.delete(cot)
    db.session.commit()
    flash("Cotización eliminada.", "ok")
    return redirect(url_for("cotizaciones.lista"))


@bp.route("/<int:ident>/correo", methods=["POST"])
def preparar_correo(ident):
    borrador = servicio_correo.borrador_cotizacion(obtener(Cotizacion, ident))
    return redirect(url_for("correos.editar", ident=borrador.id))
