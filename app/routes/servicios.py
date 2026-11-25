from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from .. import db
from ..models import GRUPOS_ANTICIPO, UNIDADES, ItemCotizacion, Servicio, Tarifa, _clave, asignar_codigos
from . import a_numero, obtener

bp = Blueprint("servicios", __name__, url_prefix="/servicios")


@bp.route("/", methods=["GET", "POST"])
def lista():
    if request.method == "POST":
        ident = request.form.get("id")
        servicio = obtener(Servicio, int(ident)) if ident else Servicio()
        servicio.nombre = request.form.get("nombre", "").strip()
        servicio.descripcion = request.form.get("descripcion", "").strip()
        servicio.categoria = request.form.get("categoria", "").strip()
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
            asignar_codigos()
            db.session.commit()
            flash("Servicio guardado.", "ok")
        return redirect(url_for("servicios.lista"))
    servicios = Servicio.query.order_by(Servicio.activo.desc(), Servicio.codigo).all()
    usos = {s.id: (Tarifa.query.filter_by(servicio_id=s.id).count(),
                   ItemCotizacion.query.filter_by(servicio_id=s.id).count()) for s in servicios}
    por_nombre = {}
    for s in servicios:
        por_nombre.setdefault(_clave(s.nombre), []).append(s)
    gemelos = {s.id: [o for o in grupo if o.id != s.id] for grupo in por_nombre.values() if len(grupo) > 1
               for s in grupo}
    return render_template("servicios/lista.html", servicios=servicios, grupos=GRUPOS_ANTICIPO, unidades=UNIDADES,
                           usos=usos, gemelos=gemelos, solo_duplicados=request.args.get("duplicados") == "1")


@bp.route("/<int:ident>/eliminar", methods=["POST"])
def eliminar(ident):
    """Elimina un servicio sin uso, o lo fusiona con otro (sus tarifas y cotizaciones pasan al destino)."""
    servicio = obtener(Servicio, ident)
    destino = db.session.get(Servicio, request.form.get("destino_id", type=int) or 0)
    n_tarifas = Tarifa.query.filter_by(servicio_id=servicio.id).count()
    n_items = ItemCotizacion.query.filter_by(servicio_id=servicio.id).count()
    nombre = f"{servicio.codigo} · {servicio.nombre}"
    if destino and destino.id != servicio.id:
        if not current_user.es_admin:
            abort(403)
        Tarifa.query.filter_by(servicio_id=servicio.id).update({"servicio_id": destino.id})
        ItemCotizacion.query.filter_by(servicio_id=servicio.id).update({"servicio_id": destino.id})
        db.session.delete(servicio)
        db.session.commit()
        flash(f"«{nombre}» se fusionó con «{destino.codigo} · {destino.nombre}»: "
              f"{n_tarifas} tarifas y {n_items} líneas de cotización pasaron al servicio que se conserva.", "ok")
    elif n_tarifas or n_items:
        flash(f"«{nombre}» se usa en {n_tarifas} tarifas y {n_items} líneas de cotización. "
              "Fusiónalo con el servicio que se queda para no perder nada.", "error")
    else:
        db.session.delete(servicio)
        db.session.commit()
        flash(f"Servicio «{nombre}» eliminado.", "ok")
    return redirect(url_for("servicios.lista"))
