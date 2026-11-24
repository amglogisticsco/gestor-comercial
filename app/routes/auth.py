from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user

from .. import db
from ..models import Empresa, Usuario

bp = Blueprint("auth", __name__)


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    if Usuario.query.count() > 0:
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        clave = request.form.get("clave", "")
        empresa_nombre = request.form.get("empresa", "").strip()
        if not nombre or not email or len(clave) < 8:
            flash("Completa todos los campos. La contraseña debe tener al menos 8 caracteres.", "error")
        else:
            usuario = Usuario(nombre=nombre, email=email)
            usuario.set_password(clave)
            db.session.add(usuario)
            if empresa_nombre:
                Empresa.actual().nombre = empresa_nombre
            db.session.commit()
            login_user(usuario, remember=True)
            flash("Cuenta creada. Completa los datos de tu empresa para empezar.", "ok")
            return redirect(url_for("configuracion.empresa"))
    return render_template("auth/setup.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if Usuario.query.count() == 0:
        return redirect(url_for("auth.setup"))
    if request.method == "POST":
        usuario = Usuario.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
        if usuario and usuario.check_password(request.form.get("clave", "")):
            login_user(usuario, remember=True)
            destino = request.args.get("next", "")
            return redirect(destino if destino.startswith("/") and not destino.startswith("//") else url_for("panel.inicio"))
        flash("Correo o contraseña incorrectos.", "error")
    return render_template("auth/login.html", empresa=Empresa.actual())


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
