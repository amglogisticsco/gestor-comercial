from flask import Blueprint, flash, redirect, render_template, request, url_for

from .. import db
from ..models import GRUPOS_ANTICIPO, Servicio
from . import a_numero, obtener

bp = Blueprint("servicios", __name__, url_prefix="/servicios")


@bp.route("/", methods=["GET", "POST"])
def lista():
    if request.method == "POST":
        ident = request.form.get("id")
        servicio = obtener(Servicio, int(ident)) if ident else Servicio()
        servicio.nombre = request.form.get("nombre", "").strip()
        servicio.descripcion = request.form.get("descripcion", "").strip()
        servicio.unidad = request.form.get("unidad", "").strip() or "Servicio"
        servicio.precio = a_numero(request.form.get("precio"))
        servicio.aplica_iva = request.form.get("aplica_iva") == "1"
        servicio.activo = request.form.get("activo", "1") == "1"
        servicio.grupo = request.form.get("grupo") if request.form.get("grupo") in GRUPOS_ANTICIPO else GRUPOS_ANTICIPO[-1]
        if not servicio.nombre:
            flash("El nombre del servicio es obligatorio.", "error")
        else:
            if not ident:
                db.session.add(servicio)
            db.session.commit()
            flash("Servicio guardado.", "ok")
        return redirect(url_for("servicios.lista"))
    return render_template("servicios/lista.html",
                           servicios=Servicio.query.order_by(Servicio.activo.desc(), Servicio.nombre).all(),
                           grupos=GRUPOS_ANTICIPO)
