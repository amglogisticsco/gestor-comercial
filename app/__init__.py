"""Gestor Comercial: clientes, cotizaciones, anticipos, correos y cumpleaños."""
import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, redirect, request, session, url_for
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
login_manager = LoginManager()

ENDPOINTS_ABIERTOS = {"auth.login", "auth.setup", "static", "configuracion.logo"}


def create_app(config_extra=None):
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    # DATA_DIR: carpeta persistente (en Render, el disco montado en /var/data)
    instancia = Path(os.getenv("DATA_DIR") or app.instance_path)
    instancia.mkdir(parents=True, exist_ok=True)

    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY") or secrets.token_hex(32),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", f"sqlite:///{instancia / 'gestor.db'}"),
        UPLOAD_DIR=str(instancia / "uploads"),
        BANDEJA_PRUEBA=str(instancia / "correos_prueba"),
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,
        ZONA_HORARIA=os.getenv("ZONA_HORARIA", "America/Bogota"),
        CUMPLE_HORA=int(os.getenv("CUMPLE_HORA", "8")),
        PROGRAMADOR=os.getenv("PROGRAMADOR", "1") == "1",
        SMTP_MODO=os.getenv("SMTP_MODO", "archivo"),  # "smtp" envía de verdad; "archivo" guarda .eml
        SMTP_HOST=os.getenv("SMTP_HOST", ""),
        SMTP_PORT=int(os.getenv("SMTP_PORT", "587")),
        SMTP_USUARIO=os.getenv("SMTP_USUARIO", ""),
        SMTP_CLAVE=os.getenv("SMTP_CLAVE", ""),
        SMTP_SEGURIDAD=os.getenv("SMTP_SEGURIDAD", "tls"),  # tls | ssl | ninguna
        SMTP_REMITENTE=os.getenv("SMTP_REMITENTE", ""),
        SMTP_COPIA_OCULTA=os.getenv("SMTP_COPIA_OCULTA", ""),
    )
    if config_extra:
        app.config.update(config_extra)
    Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)

    logging.getLogger("weasyprint").setLevel(logging.ERROR)
    logging.getLogger("fontTools").setLevel(logging.ERROR)
    db.init_app(app)
    login_manager.init_app(app)

    from . import filtros, models  # noqa: F401
    from .routes import (anticipos, auth, clientes, configuracion, correos, cotizaciones, directorio, panel, servicios,
                         tarifas, usuarios)

    filtros.registrar(app)
    for modulo in (auth, panel, directorio, clientes, servicios, tarifas, cotizaciones, anticipos, correos, configuracion,
                   usuarios):
        app.register_blueprint(modulo.bp)

    @app.before_request
    def seguridad():
        if request.method == "POST":
            token = session.get("_csrf")
            if not token or token != request.form.get("_csrf"):
                abort(400, "Formulario vencido. Recarga la página e inténtalo de nuevo.")
        if request.endpoint in ENDPOINTS_ABIERTOS or request.endpoint is None:
            return None
        if not current_user.is_authenticated:
            if models.Usuario.query.count() == 0:
                return redirect(url_for("auth.setup"))
            return redirect(url_for("auth.login", next=request.path))
        return None

    @app.after_request
    def sin_cache(respuesta):
        if respuesta.mimetype == "text/html":
            respuesta.headers["Cache-Control"] = "no-store, max-age=0"
        return respuesta

    @app.context_processor
    def utilidades():
        def csrf_token():
            if "_csrf" not in session:
                session["_csrf"] = secrets.token_hex(16)
            return session["_csrf"]

        def correos_pendientes():
            return models.Correo.query.filter(models.Correo.estado.in_(["borrador", "error"])).count()

        return {"csrf_token": csrf_token, "empresa_global": models.Empresa.actual,
                "correos_pendientes": correos_pendientes}

    with app.app_context():
        db.create_all()
        models.asegurar_columnas()
        models.sembrar_datos()

    if app.config["PROGRAMADOR"]:
        from .services.programador import iniciar

        iniciar(app)

    return app
