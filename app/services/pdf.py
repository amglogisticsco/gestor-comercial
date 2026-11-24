from pathlib import Path

from flask import current_app, render_template
from weasyprint import HTML

from ..models import Empresa


def logo_uri(empresa):
    if not empresa.logo:
        return None
    ruta = Path(current_app.config["UPLOAD_DIR"]) / empresa.logo
    return ruta.resolve().as_uri() if ruta.exists() else None


def generar(plantilla, **contexto):
    empresa = Empresa.actual()
    html = render_template(plantilla, empresa=empresa, logo=logo_uri(empresa), **contexto)
    return HTML(string=html, base_url=current_app.root_path).write_pdf()


def pdf_cotizacion(cotizacion):
    return generar("pdf/cotizacion.html", c=cotizacion)


def pdf_anticipo(anticipo):
    return generar("pdf/anticipo.html", a=anticipo)
