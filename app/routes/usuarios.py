from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from .. import db
from ..models import ROLES, Usuario
from . import obtener

bp = Blueprint("usuarios", __name__)


def solo_admin(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if not current_user.es_admin:
            abort(403)
        return vista(*args, **kwargs)
    return envoltura


def _quedaria_sin_admin(usuario, nuevo_rol, nuevo_activo):
    if not usuario.es_admin or (nuevo_rol == "admin" and nuevo_activo):
        return False
    return Usuario.query.filter(Usuario.rol == "admin", Usuario.activo.is_(True), Usuario.id != usuario.id).count() == 0


@bp.route("/usuarios/")
@solo_admin
def lista():
    return render_template("usuarios/lista.html", usuarios=Usuario.query.order_by(Usuario.activo.desc(), Usuario.nombre).all(),
                           roles=ROLES)


@bp.route("/usuarios/nuevo", methods=["GET", "POST"])
@bp.route("/usuarios/<int:ident>", methods=["GET", "POST"])
@solo_admin
def editar(ident=None):
    usuario = obtener(Usuario, ident) if ident else Usuario(rol="usuario", activo=True)
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        rol = request.form.get("rol") if request.form.get("rol") in ROLES else "usuario"
        activo = request.form.get("activo", "1") == "1"
        clave = request.form.get("clave", "")
        repetida = Usuario.query.filter(Usuario.email == email, Usuario.id != (usuario.id or 0)).first()
        error = None
        if not request.form.get("nombre", "").strip() or not email:
            error = "El nombre y el correo son obligatorios."
        elif repetida:
            error = "Ya existe un usuario con ese correo."
        elif not usuario.id and len(clave) < 8:
            error = "La contraseña debe tener al menos 8 caracteres."
        elif clave and len(clave) < 8:
            error = "La nueva contraseña debe tener al menos 8 caracteres."
        elif usuario.id and _quedaria_sin_admin(usuario, rol, activo):
            error = "Debe quedar al menos un administrador activo."
        if error:
            flash(error, "error")
        else:
            usuario.nombre = request.form.get("nombre", "").strip()
            usuario.email = email
            usuario.cargo = request.form.get("cargo", "").strip()
            usuario.telefono = request.form.get("telefono", "").strip()
            usuario.rol, usuario.activo = rol, activo
            if clave:
                usuario.set_password(clave)
            if not usuario.id:
                db.session.add(usuario)
            db.session.commit()
            flash("Usuario guardado." + (" Comparte la contraseña con la persona de forma segura." if clave else ""), "ok")
            return redirect(url_for("usuarios.lista"))
    return render_template("usuarios/form.html", u=usuario, roles=ROLES)


@bp.route("/cuenta", methods=["GET", "POST"])
def cuenta():
    if request.method == "POST":
        actual, nueva = request.form.get("clave_actual", ""), request.form.get("clave_nueva", "")
        current_user.nombre = request.form.get("nombre", "").strip() or current_user.nombre
        current_user.cargo = request.form.get("cargo", "").strip()
        current_user.telefono = request.form.get("telefono", "").strip()
        if nueva:
            if not current_user.check_password(actual):
                flash("La contraseña actual no es correcta.", "error")
                db.session.rollback()
                return redirect(url_for("usuarios.cuenta"))
            if len(nueva) < 8 or nueva != request.form.get("clave_confirmar", ""):
                flash("La nueva contraseña debe tener 8 caracteres o más y coincidir en ambos campos.", "error")
                db.session.rollback()
                return redirect(url_for("usuarios.cuenta"))
            current_user.set_password(nueva)
        db.session.commit()
        flash("Tus datos se guardaron." + (" Contraseña actualizada." if nueva else ""), "ok")
        return redirect(url_for("usuarios.cuenta"))
    return render_template("usuarios/cuenta.html")
