"""Importa el libro de cotizaciones de AMG (.xlsx/.xlsm): hojas Clientes, Servicios, Tarifas,
BD_Cotizaciones y BD_Detalle. Solo lee datos; las macros del archivo nunca se ejecutan."""
import re
from datetime import date, datetime

import openpyxl

from .. import db
from ..models import (GRUPOS_ANTICIPO, Cliente, Cotizacion, Empresa, ItemCotizacion, Servicio, Tarifa, _clave,
                      asignar_codigos)

ESTADOS_EXCEL = {"borrador": "borrador", "enviada": "enviada", "aceptada": "aprobada",
                 "rechazada": "rechazada", "vencida": "enviada"}
MODALIDADES_EXCEL = {"maritimo": "Marítimo", "aereo": "Aéreo", "terrestre": "Terrestre", "multimodal": "Multimodal"}


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = str(valor).replace("‪", "").replace("‬", "").replace("\xa0", " ")
    return " ".join(texto.split())


def _numero(valor):
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        return float(_texto(valor).replace(",", "."))
    except ValueError:
        return 0.0


def _fecha(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return None


def _filas(hoja, fila_encabezado=1):
    """Devuelve dicts {encabezado_normalizado: valor} desde la fila de encabezados."""
    filas = list(hoja.iter_rows(min_row=fila_encabezado, values_only=True))
    if not filas:
        return []
    encabezados = [_clave(_texto(c)) for c in filas[0]]
    return [dict(zip(encabezados, fila)) for fila in filas[1:] if any(v not in (None, "") for v in fila)]


def _buscar_hoja(libro, nombre):
    for hoja in libro.worksheets:
        if _clave(hoja.title) == _clave(nombre):
            return hoja
    return None


def _fila_encabezado(hoja, primera_columna):
    for i, fila in enumerate(hoja.iter_rows(max_row=30, values_only=True), start=1):
        if fila and _clave(_texto(fila[0])) == _clave(primera_columna):
            return i
    return 1


def importar(archivo, incluir_cotizaciones=True):
    libro = openpyxl.load_workbook(archivo, data_only=True, read_only=False)
    resumen = {"clientes": 0, "servicios": 0, "tarifas": 0, "cotizaciones": 0, "omitidas": []}
    empresa = Empresa.actual()

    # --- Clientes ---------------------------------------------------------
    hoja = _buscar_hoja(libro, "Clientes")
    mapa_clientes = {}
    if hoja is not None:
        for fila in _filas(hoja):
            nombre = _texto(fila.get("razon social"))
            codigo = _texto(fila.get("id cliente"))
            nit = _texto(fila.get("nit"))
            if not nombre:
                continue
            if empresa.nit and nit == empresa.nit or _clave(nombre) == _clave(empresa.nombre):
                continue  # la propia empresa no es un cliente
            cliente = (Cliente.query.filter_by(codigo=codigo).first() if codigo else None) \
                or (Cliente.query.filter_by(nit=nit).first() if nit else None) \
                or Cliente.query.filter(Cliente.razon_social.ilike(nombre)).first()
            if cliente is None:
                cliente = Cliente(razon_social=nombre)
                db.session.add(cliente)
                resumen["clientes"] += 1
            if codigo and not Cliente.query.filter(Cliente.codigo == codigo, Cliente.id != (cliente.id or 0)).first():
                cliente.codigo = codigo
            cliente.razon_social = nombre
            cliente.nit = nit or cliente.nit
            cliente.contacto_nombre = _texto(fila.get("contacto")).title() or cliente.contacto_nombre
            cliente.telefono = _texto(fila.get("telefono")) or cliente.telefono
            cliente.telefono_empresa = _texto(fila.get("telefono empresa")) or cliente.telefono_empresa
            cliente.email = _texto(fila.get("correo")).lower() or cliente.email
            cliente.ciudad = _texto(fila.get("ciudad")) or cliente.ciudad
            cliente.pais = _texto(fila.get("pais")) or cliente.pais or "Colombia"
            cliente.direccion = _texto(fila.get("direccion")) or cliente.direccion
            cliente.notas = _texto(fila.get("observaciones")) or cliente.notas
            cliente.activo = _texto(fila.get("activo")).upper() != "NO"
            db.session.flush()
            if codigo:
                mapa_clientes[codigo] = cliente

    # --- Servicios --------------------------------------------------------
    hoja = _buscar_hoja(libro, "Servicios")
    mapa_servicios = {s.codigo: s for s in Servicio.query.all() if s.codigo}
    if hoja is not None:
        # Las tarifas solo se enlazan con los códigos definidos en la hoja Servicios del archivo,
        # para no cruzarlas con servicios de la app que tengan el mismo código por coincidencia.
        mapa_servicios = {}
        por_nombre = {_clave(s.nombre): s for s in Servicio.query.all()}
        for fila in _filas(hoja):
            codigo, nombre = _texto(fila.get("codigo")), _texto(fila.get("servicio"))
            if not nombre:
                continue
            servicio = (Servicio.query.filter_by(codigo=codigo).first() if codigo else None) \
                or por_nombre.get(_clave(nombre))
            if servicio is None:
                servicio = Servicio(nombre=nombre, grupo=GRUPOS_ANTICIPO[1])
                db.session.add(servicio)
                resumen["servicios"] += 1
            if codigo and (not servicio.codigo or servicio.codigo == codigo) \
                    and not Servicio.query.filter(Servicio.codigo == codigo, Servicio.id != (servicio.id or 0)).first():
                servicio.codigo = codigo
            servicio.categoria = _texto(fila.get("categoria")) or servicio.categoria
            servicio.unidad = _texto(fila.get("unidad")) or servicio.unidad
            servicio.descripcion = _texto(fila.get("descripcion")) or servicio.descripcion
            servicio.activo = _texto(fila.get("activo")).upper() != "NO"
            db.session.flush()
            if codigo:
                mapa_servicios[codigo] = servicio

    # --- Tarifas ----------------------------------------------------------
    hoja = _buscar_hoja(libro, "Tarifas")
    if hoja is not None:
        for fila in _filas(hoja):
            codigo = _texto(fila.get("codigo tarifa"))
            codigo_servicio = _texto(fila.get("codigo servicio"))
            servicio = mapa_servicios.get(codigo_servicio) or (
                None if _buscar_hoja(libro, "Servicios") is not None
                else Servicio.query.filter_by(codigo=codigo_servicio).first())
            valor = _numero(fila.get("tarifa"))
            origen, destino, proveedor = (_texto(fila.get(k)) for k in ("origen", "destino", "proveedor"))
            if not (valor or origen or destino or proveedor):
                continue  # filas de plantilla vacías
            if not servicio:
                resumen["omitidas"].append(f"{codigo} (el servicio {codigo_servicio} no existe en la hoja Servicios)")
                continue
            tarifa = Tarifa.query.filter_by(codigo=codigo).first() if codigo else None
            if tarifa is None:
                tarifa = Tarifa(codigo=codigo)
                db.session.add(tarifa)
                resumen["tarifas"] += 1
            tarifa.servicio = servicio
            id_cliente = _texto(fila.get("id cliente") or fila.get("cliente"))
            if id_cliente:  # columna opcional para tarifas especiales por cliente
                especial = mapa_clientes.get(id_cliente) or Cliente.query.filter(
                    (Cliente.codigo == id_cliente) | Cliente.razon_social.ilike(id_cliente)).first()
                tarifa.cliente_id = especial.id if especial else None
            proceso = _texto(fila.get("proceso"))
            if proceso:
                tarifa.proceso = proceso
            tarifa.origen, tarifa.destino, tarifa.proveedor = origen, destino, proveedor
            tarifa.moneda = (_texto(fila.get("moneda")) or "USD").upper()[:3]
            tarifa.valor = valor
            tarifa.vigencia_desde = _fecha(fila.get("vigencia desde"))
            tarifa.vigencia_hasta = _fecha(fila.get("vigencia hasta"))
            tarifa.observaciones = _texto(fila.get("observaciones"))
            tarifa.activo = _texto(fila.get("activo")).upper() != "NO"
            db.session.flush()

    # --- Historial de cotizaciones ----------------------------------------
    hoja_cot, hoja_det = _buscar_hoja(libro, "BD_Cotizaciones"), _buscar_hoja(libro, "BD_Detalle")
    if incluir_cotizaciones and hoja_cot is not None:
        detalle = {}
        if hoja_det is not None:
            for fila in _filas(hoja_det):
                numero = _texto(fila.get("cotizacion no."))
                if numero:
                    detalle.setdefault(numero, []).append(fila)
        for fila in _filas(hoja_cot, _fila_encabezado(hoja_cot, "Cotización No.")):
            numero = _texto(fila.get("cotizacion no."))
            cliente = mapa_clientes.get(_texto(fila.get("id cliente")))
            if not re.match(r"^COT-\d+$", numero) or not _texto(fila.get("id cliente")):
                continue  # filas de plantilla vacías
            if cliente is None:
                resumen["omitidas"].append(f"{numero} (cliente no encontrado)")
                continue
            if Cotizacion.query.filter_by(numero=numero).first():
                continue
            fecha = _fecha(fila.get("fecha")) or date.today()
            vence = _fecha(fila.get("vigencia"))
            moneda = (_texto(fila.get("moneda")) or "USD").upper()[:3]
            cot = Cotizacion(
                numero=numero, cliente=cliente, fecha=fecha, moneda=moneda,
                validez_dias=(vence - fecha).days if vence and vence > fecha else empresa.validez_dias,
                estado=ESTADOS_EXCEL.get(_clave(_texto(fila.get("estado"))), "borrador"),
                origen=_texto(fila.get("origen")), destino=_texto(fila.get("destino")),
                modalidad=MODALIDADES_EXCEL.get(_clave(_texto(fila.get("modalidad"))), _texto(fila.get("modalidad"))),
                incoterm=_texto(fila.get("incoterm"))[:5], tipo_carga=_texto(fila.get("tipo de carga")),
                contenedor=_texto(fila.get("contenedor")), peso_kg=_texto(fila.get("peso/volumen")),
                tiempo_transito=_texto(fila.get("tiempo transito")), condicion_pago=_texto(fila.get("condicion pago")),
                notas=_texto(fila.get("observaciones")), condiciones=empresa.condiciones,
                nota_tarifas=empresa.nota_tarifas, iva_pct=empresa.iva_pct,
            )
            items = []
            for n, linea in enumerate(detalle.get(numero, [])):
                servicio = mapa_servicios.get(_texto(linea.get("codigo servicio")))
                subtotal = _numero(linea.get("cantidad") or 1) * _numero(linea.get("tarifa"))
                impuesto = _numero(linea.get("impuestos"))
                items.append(ItemCotizacion(
                    orden=n, servicio_id=servicio.id if servicio else None,
                    descripcion=_texto(linea.get("descripcion")) or (servicio.nombre if servicio else "Servicio"),
                    cantidad=_numero(linea.get("cantidad")) or 1,
                    unidad=_texto(linea.get("unidad")) or (servicio.unidad if servicio else "Servicio"),
                    precio=_numero(linea.get("tarifa")), aplica_iva=impuesto > 0,
                    observacion=_texto(linea.get("observaciones")),
                ))
                if impuesto and subtotal:
                    cot.iva_pct = round(impuesto / subtotal * 100, 2)
            if cliente.es_exterior and not any(i.aplica_iva for i in items):
                cot.iva_pct = 0
            cot.items = items
            db.session.add(cot)
            resumen["cotizaciones"] += 1

    asignar_codigos()
    db.session.commit()
    return resumen
