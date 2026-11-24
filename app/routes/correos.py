from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .. import db
from ..models import Cliente, Correo, Empresa
from ..services import correo as servicio_correo
from . import obtener

bp = Blueprint("correos", __name__, url_prefix="/correos")

TIPOS = {"cotizacion": "Cotización", "anticipo": "Anticipo", "cumpleanos": "Cumpleaños", "libre": "Mensaje"}


@bp.route("/")
def lista():
    vista = request.args.get("vista", "pendientes")
    consulta = Correo.query
    if vista == "enviados":
        consulta = consulta.filter_by(estado="enviado")
    else:
        consulta = consulta.filter(Correo.estado.in_(["borrador", "error"]))
    return render_template("correos/lista.html", correos=consulta.order_by(Correo.id.desc()).all(),
                           vista=vista, tipos=TIPOS)


@bp.route("/nuevo/<int:cliente_id>", methods=["POST"])
def nuevo(cliente_id):
    borrador = servicio_correo.borrador_libre(obtener(Cliente, cliente_id))
    return redirect(url_for("correos.editar", ident=borrador.id))


@bp.route("/<int:ident>", methods=["GET", "POST"])
def editar(ident):
    correo = obtener(Correo, ident)
    if correo.estado == "enviado":
        return render_template("correos/ver.html", correo=correo, tipos=TIPOS,
                               firma=servicio_correo.firma(Empresa.actual()))
    if request.method == "POST":
        for campo in ("para", "cc", "asunto", "cuerpo"):
            setattr(correo, campo, request.form.get(campo, "").strip())
        db.session.commit()
        if request.form.get("accion") == "enviar":
            if servicio_correo.enviar(correo):
                destino = "guardado en la bandeja de prueba" if current_app.config["SMTP_MODO"] != "smtp" else "enviado"
                flash(f"Correo {destino} a {correo.para}.", "ok")
                return redirect(url_for("correos.lista", vista="enviados"))
            flash(f"No se pudo enviar: {correo.error}", "error")
        else:
            flash("Borrador guardado.", "ok")
        return redirect(url_for("correos.editar", ident=correo.id))
    return render_template("correos/editar.html", correo=correo, tipos=TIPOS,
                           firma=servicio_correo.firma(Empresa.actual()),
                           modo_prueba=current_app.config["SMTP_MODO"] != "smtp")


@bp.route("/<int:ident>/eliminar", methods=["POST"])
def eliminar(ident):
    correo = obtener(Correo, ident)
    if correo.estado != "enviado":
        db.session.delete(correo)
        db.session.commit()
        flash("Borrador descartado.", "ok")
    return redirect(url_for("correos.lista"))
