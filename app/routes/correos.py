import mimetypes
import uuid
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from .. import db
from ..models import ArchivoCorreo, Cliente, Correo, Empresa, Proveedor
from ..services import correo as servicio_correo
from . import obtener

bp = Blueprint("correos", __name__, url_prefix="/correos")

EXTENSIONES = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".xlsx", ".xls", ".xlsm", ".csv", ".docx", ".doc",
               ".pptx", ".txt", ".zip", ".rar", ".7z", ".xml", ".eml", ".msg"}
LIMITE_TOTAL = 15 * 1024 * 1024  # lo que aceptan la mayoría de servidores de correo

TIPOS = {"cotizacion": "Cotización", "anticipo": "Solicitud de fondos", "cumpleanos": "Cumpleaños", "libre": "Mensaje", "proveedor": "Solicitud a proveedor"}


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


@bp.route("/nuevo-proveedor/<int:proveedor_id>", methods=["POST"])
def nuevo_proveedor(proveedor_id):
    borrador = servicio_correo.borrador_libre_proveedor(obtener(Proveedor, proveedor_id))
    return redirect(url_for("correos.editar", ident=borrador.id))


def _guardar_campos(correo):
    for campo in ("para", "cc", "asunto", "cuerpo"):
        if campo in request.form:
            setattr(correo, campo, request.form.get(campo, "").strip())


def _guardar_archivos(correo):
    """Guarda los archivos subidos; devuelve cuántos se agregaron."""
    carpeta = Path(current_app.config["UPLOAD_DIR"]) / "adjuntos" / str(correo.id)
    total, agregados = correo.tamano_archivos, 0
    for archivo in request.files.getlist("archivos"):
        if not archivo or not archivo.filename:
            continue
        nombre = archivo.filename.replace("/", "_").replace("\\", "_").strip()
        extension = Path(nombre).suffix.lower()
        if extension not in EXTENSIONES:
            flash(f"«{nombre}» no se adjuntó: tipo de archivo no permitido.", "error")
            continue
        contenido = archivo.read()
        if total + len(contenido) > LIMITE_TOTAL:
            flash(f"«{nombre}» no se adjuntó: los adjuntos superarían 15 MB.", "error")
            continue
        carpeta.mkdir(parents=True, exist_ok=True)
        guardado = f"{uuid.uuid4().hex[:10]}_{secure_filename(nombre) or 'archivo' + extension}"
        (carpeta / guardado).write_bytes(contenido)
        db.session.add(ArchivoCorreo(correo=correo, nombre=nombre, archivo=f"adjuntos/{correo.id}/{guardado}",
                                     tipo=archivo.mimetype or mimetypes.guess_type(nombre)[0] or "application/octet-stream",
                                     tamano=len(contenido)))
        total += len(contenido)
        agregados += 1
    return agregados


@bp.route("/<int:ident>", methods=["GET", "POST"])
def editar(ident):
    correo = obtener(Correo, ident)
    if correo.estado == "enviado":
        return render_template("correos/ver.html", correo=correo, tipos=TIPOS,
                               firma=servicio_correo.firma(Empresa.actual()))
    if request.method == "POST":
        _guardar_campos(correo)
        agregados = _guardar_archivos(correo)
        db.session.commit()
        if request.form.get("accion") == "adjuntar":
            if agregados:
                flash(f"{agregados} {'archivo adjuntado' if agregados == 1 else 'archivos adjuntados'}.", "ok")
            return redirect(url_for("correos.editar", ident=correo.id) + "#adjuntos")
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
                           firma=servicio_correo.firma(Empresa.actual()), idiomas=servicio_correo.IDIOMAS,
                           modo_prueba=current_app.config["SMTP_MODO"] != "smtp")


@bp.route("/<int:ident>/archivos/<int:archivo_id>/quitar", methods=["POST"])
def quitar_archivo(ident, archivo_id):
    correo = obtener(Correo, ident)
    archivo = obtener(ArchivoCorreo, archivo_id)
    if archivo.correo_id != correo.id or correo.estado == "enviado":
        abort(404)
    _guardar_campos(correo)
    db.session.delete(archivo)
    db.session.commit()
    flash(f"Se quitó «{archivo.nombre}».", "ok")
    return redirect(url_for("correos.editar", ident=correo.id) + "#adjuntos")


@bp.route("/<int:ident>/archivos/<int:archivo_id>")
def descargar_archivo(ident, archivo_id):
    archivo = obtener(ArchivoCorreo, archivo_id)
    if archivo.correo_id != ident or not archivo.ruta.exists():
        abort(404)
    return send_file(archivo.ruta, download_name=archivo.nombre, as_attachment=True, mimetype=archivo.tipo)


@bp.route("/<int:ident>/idioma", methods=["POST"])
def idioma(ident):
    correo = obtener(Correo, ident)
    nuevo = request.form.get("idioma")
    if correo.estado != "enviado" and nuevo in servicio_correo.IDIOMAS:
        for campo in ("para", "cc"):  # conserva los destinatarios que ya se escribieron
            if campo in request.form:
                setattr(correo, campo, request.form.get(campo, "").strip())
        servicio_correo.cambiar_idioma(correo, nuevo)
        flash("Borrador en inglés." if nuevo == "en" else "Borrador en español.", "ok")
    return redirect(url_for("correos.editar", ident=correo.id))


@bp.route("/<int:ident>/eliminar", methods=["POST"])
def eliminar(ident):
    correo = obtener(Correo, ident)
    if correo.estado != "enviado":
        db.session.delete(correo)
        db.session.commit()
        flash("Borrador descartado.", "ok")
    return redirect(url_for("correos.lista"))
