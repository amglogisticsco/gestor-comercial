from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_from_directory, url_for

from .. import db
from ..models import MONEDAS, Empresa
from . import a_numero

bp = Blueprint("configuracion", __name__, url_prefix="/configuracion")

EXTENSIONES_LOGO = {".png", ".jpg", ".jpeg", ".svg"}
CAMPOS = ["nombre", "nit", "direccion", "ciudad", "telefono", "email", "web", "condiciones",
          "datos_bancarios", "firma_correo", "cumple_asunto", "cumple_mensaje"]


@bp.route("/", methods=["GET", "POST"])
def empresa():
    emp = Empresa.actual()
    if request.method == "POST":
        for campo in CAMPOS:
            setattr(emp, campo, request.form.get(campo, "").strip())
        emp.moneda = request.form.get("moneda", "COP")
        emp.iva_pct = a_numero(request.form.get("iva_pct"), 19)
        emp.validez_dias = request.form.get("validez_dias", type=int) or 15
        emp.anticipo_pct = a_numero(request.form.get("anticipo_pct"), 50)
        color = request.form.get("color", "").strip()
        emp.color = color if color.startswith("#") and len(color) in (4, 7) else "#12304F"
        emp.cumple_auto_envio = request.form.get("cumple_auto_envio") == "1"

        logo = request.files.get("logo")
        if logo and logo.filename:
            extension = Path(logo.filename).suffix.lower()
            if extension not in EXTENSIONES_LOGO:
                flash("El logo debe ser PNG, JPG o SVG.", "error")
            else:
                nombre = f"logo{extension}"
                logo.save(Path(current_app.config["UPLOAD_DIR"]) / nombre)
                emp.logo = nombre
        if request.form.get("quitar_logo") == "1":
            emp.logo = ""
        db.session.commit()
        flash("Configuración guardada.", "ok")
        return redirect(url_for("configuracion.empresa"))

    cfg = current_app.config
    smtp = {
        "modo": cfg["SMTP_MODO"], "host": cfg["SMTP_HOST"], "puerto": cfg["SMTP_PORT"],
        "usuario": cfg["SMTP_USUARIO"], "remitente": cfg["SMTP_REMITENTE"] or emp.email,
        "seguridad": cfg["SMTP_SEGURIDAD"], "bandeja": cfg["BANDEJA_PRUEBA"],
    }
    return render_template("configuracion.html", e=emp, monedas=MONEDAS, smtp=smtp,
                           hora=cfg["CUMPLE_HORA"], zona=cfg["ZONA_HORARIA"])


@bp.route("/logo")
def logo():
    emp = Empresa.actual()
    return send_from_directory(current_app.config["UPLOAD_DIR"], emp.logo) if emp.logo else ("", 404)
