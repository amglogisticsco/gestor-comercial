"""Eliminación definitiva (solo administradores) de registros con historial."""
from .. import db
from ..models import Anticipo, Cliente, Correo, Cotizacion, ItemCotizacion, Proveedor, Tarifa


def _correos_de(tipo, ident):
    return Correo.query.filter_by(adjunto_tipo=tipo, adjunto_id=ident).all()


def resumen_cliente(cliente):
    tarifas = Tarifa.query.filter_by(cliente_id=cliente.id).count()
    return {"cotizaciones": len(cliente.cotizaciones), "anticipos": len(cliente.anticipos),
            "correos": len(cliente.correos), "tarifas": tarifas}


def eliminar_anticipo(anticipo):
    for correo in _correos_de("anticipo", anticipo.id):
        db.session.delete(correo)
    db.session.delete(anticipo)


def eliminar_cotizacion(cot):
    if cot.revisa_a_id:  # si se borra una revisión, la anterior vuelve a quedar vigente
        anterior = db.session.get(Cotizacion, cot.revisa_a_id)
        if anterior and anterior.reemplazada_por_id == cot.id:
            anterior.estado, anterior.reemplazada_por_id = "enviada", None
    Cotizacion.query.filter_by(revisa_a_id=cot.id).update({"revisa_a_id": None})
    for anticipo in list(cot.anticipos):
        eliminar_anticipo(anticipo)
    for correo in _correos_de("cotizacion", cot.id):
        db.session.delete(correo)
    db.session.delete(cot)


def eliminar_cliente(cliente):
    for anticipo in list(cliente.anticipos):
        eliminar_anticipo(anticipo)
    db.session.flush()
    for cot in list(cliente.cotizaciones):
        eliminar_cotizacion(cot)
    for correo in Correo.query.filter_by(cliente_id=cliente.id).all():
        db.session.delete(correo)
    for tarifa in Tarifa.query.filter_by(cliente_id=cliente.id).all():
        # Otras cotizaciones que usaron esta tarifa especial conservan sus valores
        ItemCotizacion.query.filter_by(tarifa_id=tarifa.id).update({"tarifa_id": None})
        Cotizacion.query.filter_by(tarifa_id=tarifa.id).update({"tarifa_id": None})
        db.session.delete(tarifa)
    db.session.delete(cliente)


def eliminar_proveedor(proveedor):
    """Las tarifas se conservan (quedan sin proveedor asignado, con el nombre como texto)."""
    for tarifa in list(proveedor.tarifas):
        tarifa.proveedor_id = None
    for correo in Correo.query.filter_by(proveedor_id=proveedor.id).all():
        db.session.delete(correo)
    db.session.delete(proveedor)
