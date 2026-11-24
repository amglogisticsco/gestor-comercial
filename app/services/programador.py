"""Tarea diaria: prepara los saludos de cumpleaños a la hora configurada."""
from apscheduler.schedulers.background import BackgroundScheduler

_programador = None


def iniciar(app):
    global _programador
    if _programador is not None:
        return _programador

    def tarea():
        with app.app_context():
            from .cumpleanos import preparar_saludos

            preparar_saludos()

    _programador = BackgroundScheduler(timezone=app.config["ZONA_HORARIA"], daemon=True)
    _programador.add_job(tarea, "cron", hour=app.config["CUMPLE_HORA"], minute=0, id="cumpleanos",
                         misfire_grace_time=6 * 3600, coalesce=True)
    _programador.start()
    return _programador
