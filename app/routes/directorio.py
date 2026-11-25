"""Directorio: clientes, proveedores y agentes internacionales en un solo lugar."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_

from .. import db
from ..models import (REDES_AGENTES, TIPOS_PROVEEDOR, Cliente, Cotizacion, Proveedor, Tarifa, asignar_codigos)
from ..services import correo as servicio_correo
from . import obtener

bp = Blueprint("directorio", __name__, url_prefix="/directorio")

CAMPOS = ["nombre", "nit", "contacto_nombre", "cargo", "email", "email_cc", "telefono", "telefono_empresa",
          "ciudad", "pais", "web", "red", "cobertura", "servicios_ofrecidos", "notas"]


def _buscar(modelo, columnas, q):
    patron = f"%{q}%"
    return modelo.query.filter(or_(*[c.ilike(patron) for c in columnas]))


@bp.route("/")
def inicio():
    q = request.args.get("q", "").strip()
    pestana = request.args.get("ver", "todos")
    tipo = request.args.get("tipo", "")
    inactivos = request.args.get("inactivos") == "1"

    clientes = _buscar(Cliente, [Cliente.razon_social, Cliente.codigo, Cliente.nit, Cliente.contacto_nombre,
                                 Cliente.email, Cliente.ciudad, Cliente.pais], q) if q else Cliente.query
    proveedores = _buscar(Proveedor, [Proveedor.nombre, Proveedor.codigo, Proveedor.nit, Proveedor.contacto_nombre,
                                      Proveedor.email, Proveedor.ciudad, Proveedor.pais, Proveedor.tipo,
                                      Proveedor.cobertura, Proveedor.servicios_ofrecidos, Proveedor.red], q) \
        if q else Proveedor.query
    if not inactivos:
        clientes = clientes.filter(Cliente.activo.is_(True))
        proveedores = proveedores.filter(Proveedor.activo.is_(True))
    if tipo:
        proveedores = proveedores.filter(Proveedor.tipo == tipo)
    clientes = clientes.order_by(Cliente.razon_social).all()
    todos_prov = proveedores.order_by(Proveedor.nombre).all()
    agentes = [p for p in todos_prov if p.es_agente]
    prov = [p for p in todos_prov if not p.es_agente]
    return render_template("directorio/inicio.html", q=q, pestana=pestana, tipo=tipo, inactivos=inactivos,
                           clientes=clientes, proveedores=prov, agentes=agentes,
                           tipos=[t for t in TIPOS_PROVEEDOR if t != "Agente internacional"])


@bp.route("/proveedores/nuevo", methods=["GET", "POST"])
@bp.route("/proveedores/<int:ident>/editar", methods=["GET", "POST"])
def editar(ident=None):
    p = obtener(Proveedor, ident) if ident else Proveedor(
        tipo="Agente internacional" if request.args.get("agente") else (request.args.get("tipo") or "Naviera"),
        activo=True)
    if request.method == "POST":
        for campo in CAMPOS:
            setattr(p, campo, request.form.get(campo, "").strip())
        p.email = p.email.lower()
        p.tipo = request.form.get("tipo") if request.form.get("tipo") in TIPOS_PROVEEDOR else "Otro"
        p.activo = request.form.get("activo", "1") == "1"
        if not p.nombre:
            flash("El nombre es obligatorio.", "error")
        else:
            if not p.id:
                db.session.add(p)
            asignar_codigos()
            # Mantener el nombre de proveedor de las tarifas sincronizado
            for t in p.tarifas:
                t.proveedor = p.nombre
            db.session.commit()
            flash(f"{'Agente' if p.es_agente else 'Proveedor'} {p.codigo} guardado.", "ok")
            return redirect(url_for("directorio.ver", ident=p.id))
    return render_template("directorio/form.html", p=p, tipos=TIPOS_PROVEEDOR, redes=REDES_AGENTES)


@bp.route("/proveedores/<int:ident>")
def ver(ident):
    p = obtener(Proveedor, ident)
    cotizaciones = Cotizacion.query.order_by(Cotizacion.id.desc()).limit(30).all()
    from ..models import Correo
    correos = Correo.query.filter_by(proveedor_id=p.id).order_by(Correo.id.desc()).all()
    return render_template("directorio/ver.html", p=p, cotizaciones=cotizaciones, correos=correos)


@bp.route("/proveedores/<int:ident>/pedir-cotizacion", methods=["POST"])
def pedir_cotizacion(ident):
    p = obtener(Proveedor, ident)
    cot = db.session.get(Cotizacion, request.form.get("cotizacion_id", type=int) or 0)
    idioma = "en" if request.form.get("idioma") == "en" else "es"
    borrador = servicio_correo.borrador_solicitud_tarifa(p, cot, idioma)
    return redirect(url_for("correos.editar", ident=borrador.id))


@bp.route("/proveedores/<int:ident>/eliminar", methods=["POST"])
def eliminar(ident):
    p = obtener(Proveedor, ident)
    from ..models import Correo
    from ..services import borrado

    if request.form.get("confirmar") == "ELIMINAR":
        if not current_user.es_admin:
            abort(403)
        nombre, n_tarifas = p.nombre, len(p.tarifas)
        borrado.eliminar_proveedor(p)
        db.session.commit()
        flash(f"«{nombre}» eliminado definitivamente. Sus {n_tarifas} tarifas se conservaron sin proveedor asignado.", "ok")
        return redirect(url_for("directorio.inicio"))
    if p.tarifas or Correo.query.filter_by(proveedor_id=p.id).count():
        p.activo = False
        db.session.commit()
        flash("Tiene tarifas asociadas, así que se marcó como inactivo en lugar de eliminarse.", "ok")
        return redirect(url_for("directorio.ver", ident=p.id))
    db.session.delete(p)
    db.session.commit()
    flash("Eliminado del directorio.", "ok")
    return redirect(url_for("directorio.inicio"))
