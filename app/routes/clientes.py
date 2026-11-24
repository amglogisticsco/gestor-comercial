import csv
import io

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from sqlalchemy import or_

from .. import db
from ..models import Cliente, asignar_codigos
from . import a_fecha, obtener

bp = Blueprint("clientes", __name__, url_prefix="/clientes")

CAMPOS = ["razon_social", "nit", "contacto_nombre", "cargo", "email", "email_cc", "telefono",
          "direccion", "ciudad", "pais", "notas"]


@bp.route("/")
def lista():
    q = request.args.get("q", "").strip()
    consulta = Cliente.query
    if q:
        patron = f"%{q}%"
        consulta = consulta.filter(or_(Cliente.razon_social.ilike(patron), Cliente.nit.ilike(patron), Cliente.codigo.ilike(patron),
                                       Cliente.contacto_nombre.ilike(patron), Cliente.email.ilike(patron),
                                       Cliente.ciudad.ilike(patron)))
    if request.args.get("inactivos") != "1":
        consulta = consulta.filter(Cliente.activo.is_(True))
    return render_template("clientes/lista.html", clientes=consulta.order_by(Cliente.razon_social).all(), q=q)


def _guardar(cliente):
    for campo in CAMPOS:
        setattr(cliente, campo, request.form.get(campo, "").strip())
    cliente.email = cliente.email.lower()
    cliente.fecha_nacimiento = a_fecha(request.form.get("fecha_nacimiento"))
    cliente.activo = request.form.get("activo", "1") == "1"
    if not cliente.razon_social:
        flash("El nombre o razón social es obligatorio.", "error")
        return False
    return True


@bp.route("/nuevo", methods=["GET", "POST"])
def nuevo():
    cliente = Cliente()
    if request.method == "POST" and _guardar(cliente):
        db.session.add(cliente)
        asignar_codigos()
        db.session.commit()
        flash(f"Cliente {cliente.codigo} creado.", "ok")
        return redirect(url_for("clientes.ver", ident=cliente.id))
    return render_template("clientes/form.html", cliente=cliente)


@bp.route("/<int:ident>/editar", methods=["GET", "POST"])
def editar(ident):
    cliente = obtener(Cliente, ident)
    if request.method == "POST":
        if _guardar(cliente):
            db.session.commit()
            flash("Cambios guardados.", "ok")
            return redirect(url_for("clientes.ver", ident=cliente.id))
        db.session.rollback()
    return render_template("clientes/form.html", cliente=cliente)


@bp.route("/<int:ident>")
def ver(ident):
    return render_template("clientes/ver.html", cliente=obtener(Cliente, ident))


@bp.route("/<int:ident>/eliminar", methods=["POST"])
def eliminar(ident):
    cliente = obtener(Cliente, ident)
    if cliente.cotizaciones or cliente.anticipos or cliente.correos:
        cliente.activo = False
        db.session.commit()
        flash("El cliente tiene historial, así que se marcó como inactivo en lugar de eliminarse.", "ok")
        return redirect(url_for("clientes.ver", ident=cliente.id))
    db.session.delete(cliente)
    db.session.commit()
    flash("Cliente eliminado.", "ok")
    return redirect(url_for("clientes.lista"))


@bp.route("/exportar.csv")
def exportar():
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";")
    escritor.writerow(CAMPOS + ["fecha_nacimiento", "activo"])
    for c in Cliente.query.order_by(Cliente.razon_social).all():
        escritor.writerow([getattr(c, campo) or "" for campo in CAMPOS]
                          + [c.fecha_nacimiento.isoformat() if c.fecha_nacimiento else "", "1" if c.activo else "0"])
    return Response("﻿" + salida.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=clientes.csv"})


@bp.route("/importar", methods=["GET", "POST"])
def importar():
    if request.method == "POST":
        archivo = request.files.get("archivo")
        if not archivo or not archivo.filename.lower().endswith(".csv"):
            flash("Selecciona un archivo .csv.", "error")
            return redirect(request.url)
        texto = archivo.read().decode("utf-8-sig", errors="replace")
        delimitador = ";" if texto.count(";") >= texto.count(",") else ","
        creados = omitidos = 0
        for fila in csv.DictReader(io.StringIO(texto), delimiter=delimitador):
            fila = {(k or "").strip().lower(): (v or "").strip() for k, v in fila.items()}
            if not fila.get("razon_social"):
                omitidos += 1
                continue
            if fila.get("nit") and Cliente.query.filter_by(nit=fila["nit"]).first():
                omitidos += 1
                continue
            cliente = Cliente(**{campo: fila.get(campo, "") for campo in CAMPOS})
            cliente.pais = cliente.pais or "Colombia"
            cliente.fecha_nacimiento = a_fecha(fila.get("fecha_nacimiento"))
            db.session.add(cliente)
            creados += 1
        db.session.commit()
        flash(f"Importación lista: {creados} clientes creados, {omitidos} omitidos (sin nombre o NIT repetido).", "ok")
        return redirect(url_for("clientes.lista"))
    return render_template("clientes/importar.html", campos=CAMPOS + ["fecha_nacimiento"])
