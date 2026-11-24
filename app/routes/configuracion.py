from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_from_directory, url_for

from .. import db
from ..models import MONEDAS, Empresa
from . import a_numero
from .usuarios import solo_admin

bp = Blueprint("configuracion", __name__, url_prefix="/configuracion")

EXTENSIONES_LOGO = {".png", ".jpg", ".jpeg", ".svg"}
CAMPOS = ["nombre", "nit", "direccion", "ciudad", "telefono", "email", "web", "eslogan", "condiciones",
          "nota_tarifas", "datos_bancarios", "pie_anticipo", "firma_correo", "cumple_asunto", "cumple_mensaje"]


@bp.route("/", methods=["GET", "POST"])
@solo_admin
def empresa():
    emp = Empresa.actual()
    if request.method == "POST":
        for campo in CAMPOS:
            setattr(emp, campo, request.form.get(campo, "").strip())
        emp.moneda = request.form.get("moneda", "COP")
        emp.iva_pct = a_numero(request.form.get("iva_pct"), 19)
        emp.validez_dias = request.form.get("validez_dias", type=int) or 15
        emp.anticipo_pct = a_numero(request.form.get("anticipo_pct"), 50)
        for campo, defecto in (("color", "#373435"), ("color_acento", "#ED3237")):
            color = request.form.get(campo, "").strip()
            setattr(emp, campo, color if color.startswith("#") and len(color) in (4, 7) else defecto)
        emp.cumple_auto_envio = request.form.get("cumple_auto_envio") == "1"
        emp.cot_siguiente = max(1, request.form.get("cot_siguiente", type=int) or 1)

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


@bp.route("/importar", methods=["GET", "POST"])
@solo_admin
def importar():
    if request.method == "POST":
        archivo = request.files.get("archivo")
        if not archivo or Path(archivo.filename or "").suffix.lower() not in (".xlsx", ".xlsm"):
            flash("Selecciona un archivo .xlsx o .xlsm.", "error")
            return redirect(request.url)
        from ..services.importar_excel import importar as importar_libro

        try:
            r = importar_libro(archivo.stream, incluir_cotizaciones=request.form.get("cotizaciones") == "1")
        except Exception as exc:  # archivo dañado o con otro formato
            db.session.rollback()
            current_app.logger.exception("Error importando Excel")
            flash(f"No se pudo leer el archivo: {exc}", "error")
            return redirect(request.url)
        flash(f"Importación lista: {r['clientes']} clientes, {r['servicios']} servicios, {r['tarifas']} tarifas y "
              f"{r['cotizaciones']} cotizaciones nuevas (lo existente se actualizó).", "ok")
        if r["omitidas"]:
            flash("Omitidas: " + ", ".join(r["omitidas"][:10]), "error")
        return redirect(url_for("tarifas.lista"))
    return render_template("importar_excel.html")
