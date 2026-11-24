import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import current_app
from flask_login import UserMixin
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, login_manager

ESTADOS_COTIZACION = {
    "borrador": "Borrador",
    "enviada": "Enviada",
    "aprobada": "Aprobada",
    "rechazada": "Rechazada",
    "vencida": "Vencida",
}
ROLES = {"admin": "Administrador", "usuario": "Usuario"}
ESTADOS_ANTICIPO = {"pendiente": "Pendiente", "enviada": "Enviada", "pagada": "Pagada", "anulada": "Anulada"}
TIPOS_OPERACION = ["Importación", "Exportación", "Zona Franca", "OTM", "DTA", "Proceso de aduana", "Etiquetado", "Nacional"]
MODALIDADES = ["Aérea", "Marítima FCL", "Marítima LCL", "Terrestre", "Multimodal"]
INCOTERMS = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"]
MONEDAS = ["USD", "COP", "EUR"]
CONDICIONES_PAGO = ["Prepago", "Crédito"]
TIPOS_CARGA = ["General", "Refrigerada", "Perecedera", "Peligrosa", "Sobredimensionada"]
CONTENEDORES = ["20 ST", "40 ST", "40 HC", "LCL", "Carga suelta"]
TRANSPORTISTAS = ["Maersk", "Hapag-Lloyd", "COSCO", "MSC", "CMA CGM", "Copa", "LATAM", "Avianca", "Air Cargo Pack"]
GRUPOS_ANTICIPO = ["Intermediación aduanera", "Gastos aerolínea / puerto", "Otros gastos"]


class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    cargo = db.Column(db.String(80), default="")
    telefono = db.Column(db.String(60), default="")
    rol = db.Column(db.String(20), default="usuario")  # admin | usuario
    activo = db.Column(db.Boolean, default=True)
    creado = db.Column(db.DateTime, default=datetime.now)

    @property
    def es_admin(self):
        return self.rol == "admin"

    @property
    def is_active(self):  # Flask-Login: un usuario desactivado no puede entrar
        return bool(self.activo)

    def set_password(self, clave):
        self.password_hash = generate_password_hash(clave)

    def check_password(self, clave):
        return check_password_hash(self.password_hash, clave)


@login_manager.user_loader
def cargar_usuario(uid):
    return db.session.get(Usuario, int(uid))


class Empresa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(160), default="Mi Empresa")
    nit = db.Column(db.String(40), default="")
    direccion = db.Column(db.String(200), default="")
    ciudad = db.Column(db.String(80), default="")
    telefono = db.Column(db.String(60), default="")
    email = db.Column(db.String(160), default="")
    web = db.Column(db.String(160), default="")
    eslogan = db.Column(db.String(200), default="")
    logo = db.Column(db.String(200), default="")
    color = db.Column(db.String(9), default="#373435")
    color_acento = db.Column(db.String(9), default="#ED3237")
    moneda = db.Column(db.String(3), default="USD")
    iva_pct = db.Column(db.Float, default=19.0)
    validez_dias = db.Column(db.Integer, default=15)
    anticipo_pct = db.Column(db.Float, default=50.0)
    condiciones = db.Column(db.Text, default="")
    nota_tarifas = db.Column(db.Text, default="")
    datos_bancarios = db.Column(db.Text, default="")
    pie_anticipo = db.Column(db.Text, default="")
    firma_correo = db.Column(db.Text, default="")
    cumple_auto_envio = db.Column(db.Boolean, default=False)
    cumple_asunto = db.Column(db.String(200), default="")
    cumple_mensaje = db.Column(db.Text, default="")

    @staticmethod
    def actual():
        empresa = Empresa.query.first()
        if empresa is None:
            empresa = Empresa()
            db.session.add(empresa)
            db.session.commit()
        return empresa


class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    razon_social = db.Column(db.String(160), nullable=False)
    nit = db.Column(db.String(40), default="")
    contacto_nombre = db.Column(db.String(120), default="")
    cargo = db.Column(db.String(80), default="")
    email = db.Column(db.String(160), default="")
    email_cc = db.Column(db.String(300), default="")
    telefono = db.Column(db.String(60), default="")
    direccion = db.Column(db.String(200), default="")
    ciudad = db.Column(db.String(80), default="")
    pais = db.Column(db.String(80), default="Colombia")
    fecha_nacimiento = db.Column(db.Date, nullable=True)
    notas = db.Column(db.Text, default="")
    activo = db.Column(db.Boolean, default=True)
    creado = db.Column(db.DateTime, default=datetime.now)

    cotizaciones = db.relationship("Cotizacion", back_populates="cliente", order_by="desc(Cotizacion.id)")
    anticipos = db.relationship("Anticipo", back_populates="cliente", order_by="desc(Anticipo.id)")
    correos = db.relationship("Correo", back_populates="cliente", order_by="desc(Correo.id)")

    @property
    def nombre_saludo(self):
        base = (self.contacto_nombre or self.razon_social or "").strip()
        return base.split()[0].capitalize() if base else ""

    @property
    def es_exterior(self):
        """Cliente fuera de Colombia: sus cotizaciones arrancan con IVA 0 %."""
        pais = (self.pais or "").strip().lower()
        return bool(pais) and pais not in ("colombia", "co", "col")

    def cumple_en(self, anio):
        """Fecha de cumpleaños en un año dado (29-feb pasa a 28-feb en años no bisiestos)."""
        if not self.fecha_nacimiento:
            return None
        try:
            return self.fecha_nacimiento.replace(year=anio)
        except ValueError:
            return date(anio, 2, 28)

    def proximo_cumple(self, hoy=None):
        hoy = hoy or date.today()
        fecha = self.cumple_en(hoy.year)
        if fecha is None:
            return None
        return fecha if fecha >= hoy else self.cumple_en(hoy.year + 1)

    def dias_para_cumple(self, hoy=None):
        hoy = hoy or date.today()
        proximo = self.proximo_cumple(hoy)
        return None if proximo is None else (proximo - hoy).days


class Servicio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(160), nullable=False)
    descripcion = db.Column(db.String(300), default="")
    unidad = db.Column(db.String(40), default="Servicio")
    precio = db.Column(db.Float, default=0)
    aplica_iva = db.Column(db.Boolean, default=False)
    grupo = db.Column(db.String(40), default="Otros gastos")  # grupo en la solicitud de fondos
    activo = db.Column(db.Boolean, default=True)


class Cotizacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"), nullable=False)
    fecha = db.Column(db.Date, default=date.today)
    validez_dias = db.Column(db.Integer, default=15)
    estado = db.Column(db.String(20), default="borrador")
    ejecutivo = db.Column(db.String(120), default="")
    condicion_pago = db.Column(db.String(30), default="")
    tipo_operacion = db.Column(db.String(30), default="")
    modalidad = db.Column(db.String(30), default="")
    incoterm = db.Column(db.String(5), default="")
    origen = db.Column(db.String(120), default="")
    destino = db.Column(db.String(120), default="")
    ruta = db.Column(db.String(200), default="")
    mercancia = db.Column(db.String(200), default="")
    tipo_carga = db.Column(db.String(40), default="")
    contenedor = db.Column(db.String(40), default="")
    transportista = db.Column(db.String(80), default="")
    bultos = db.Column(db.String(40), default="")  # piezas
    peso_kg = db.Column(db.String(40), default="")
    peso_vol = db.Column(db.String(40), default="")
    volumen_m3 = db.Column(db.String(40), default="")
    dimensiones = db.Column(db.String(120), default="")
    tiempo_transito = db.Column(db.String(40), default="")
    dias_libres_origen = db.Column(db.String(20), default="")
    dias_libres_destino = db.Column(db.String(20), default="")
    moneda = db.Column(db.String(3), default="USD")
    iva_pct = db.Column(db.Float, default=19.0)
    notas = db.Column(db.Text, default="")
    condiciones = db.Column(db.Text, default="")
    nota_tarifas = db.Column(db.Text, default="")
    creado = db.Column(db.DateTime, default=datetime.now)

    cliente = db.relationship("Cliente", back_populates="cotizaciones")
    items = db.relationship(
        "ItemCotizacion", back_populates="cotizacion", cascade="all, delete-orphan", order_by="ItemCotizacion.orden"
    )
    anticipos = db.relationship("Anticipo", back_populates="cotizacion")

    @property
    def subtotal(self):
        return round(sum(i.total for i in self.items), 2)

    @property
    def iva(self):
        return round(sum(i.impuesto(self.iva_pct) for i in self.items), 2)

    @property
    def total(self):
        return round(self.subtotal + self.iva, 2)

    @property
    def vence(self):
        return self.fecha + timedelta(days=self.validez_dias or 0)

    @property
    def estado_actual(self):
        if self.estado in ("borrador", "enviada") and self.vence < date.today():
            return "vencida"
        return self.estado

    @property
    def asunto(self):
        """Ej.: 'Exportación · Marítima FCL'."""
        return " · ".join(p for p in (self.tipo_operacion, self.modalidad) if p)

    @property
    def peso_volumen(self):
        partes = []
        if self.peso_kg:
            partes.append(f"{self.peso_kg} kg")
        if self.peso_vol:
            partes.append(f"{self.peso_vol} kg vol.")
        if self.volumen_m3:
            partes.append(f"{self.volumen_m3} m³")
        return " / ".join(partes)

    @property
    def datos_servicio(self):
        """Pares (etiqueta, valor) con datos, en el orden del formato de AMG."""
        pares = [
            ("Origen", self.origen), ("Destino", self.destino),
            ("Modalidad", self.modalidad), ("Incoterm", self.incoterm),
            ("Tipo de carga", self.tipo_carga), ("Contenedor", self.contenedor),
            ("Peso / Volumen", self.peso_volumen), ("Tiempo tránsito", f"{self.tiempo_transito} días" if self.tiempo_transito else ""),
            ("Naviera / Aerolínea", self.transportista), ("Piezas", self.bultos),
            ("Días libres origen", self.dias_libres_origen), ("Días libres destino", self.dias_libres_destino),
            ("Mercancía", self.mercancia), ("Dimensiones", self.dimensiones), ("Ruta", self.ruta),
        ]
        return [(k, v) for k, v in pares if v]

    @property
    def tiene_operacion(self):
        return bool(self.datos_servicio)

    @property
    def resumen(self):
        partes = [p.lower() for p in (self.tipo_operacion, self.modalidad) if p]
        ruta = self.ruta or (f"{self.origen} – {self.destino}" if self.origen and self.destino else "")
        if ruta:
            partes.append(ruta)
        return "la operación de " + " ".join(partes) if partes else "los servicios solicitados"


class ItemCotizacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cotizacion_id = db.Column(db.Integer, db.ForeignKey("cotizacion.id"), nullable=False)
    servicio_id = db.Column(db.Integer, db.ForeignKey("servicio.id"), nullable=True)
    orden = db.Column(db.Integer, default=0)
    descripcion = db.Column(db.String(300), nullable=False)
    cantidad = db.Column(db.Float, default=1)
    unidad = db.Column(db.String(40), default="Servicio")
    precio = db.Column(db.Float, default=0)
    aplica_iva = db.Column(db.Boolean, default=False)
    observacion = db.Column(db.String(120), default="")

    cotizacion = db.relationship("Cotizacion", back_populates="items")

    @property
    def total(self):
        return round((self.cantidad or 0) * (self.precio or 0), 2)

    def impuesto(self, pct):
        return round(self.total * (pct or 0) / 100, 2) if self.aplica_iva else 0.0


class Anticipo(db.Model):
    """Solicitud de fondos: tributos aduaneros + conceptos agrupados."""
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"), nullable=False)
    cotizacion_id = db.Column(db.Integer, db.ForeignKey("cotizacion.id"), nullable=True)
    fecha = db.Column(db.Date, default=date.today)
    fecha_limite = db.Column(db.Date, nullable=True)
    tipo_operacion = db.Column(db.String(30), default="Importación")
    modalidad = db.Column(db.String(30), default="")
    do_numero = db.Column(db.String(40), default="")
    aduana = db.Column(db.String(80), default="")
    origen = db.Column(db.String(120), default="")
    destino = db.Column(db.String(120), default="")
    tipo_mercancia = db.Column(db.String(200), default="")
    doc_transporte = db.Column(db.String(80), default="")
    partida_arancelaria = db.Column(db.String(40), default="")
    trm = db.Column(db.Float, default=0)
    fob = db.Column(db.Float, default=0)
    flete = db.Column(db.Float, default=0)
    seguro = db.Column(db.Float, default=0)
    otros_cif = db.Column(db.Float, default=0)
    arancel_pct = db.Column(db.Float, default=0)
    iva_tributo_pct = db.Column(db.Float, default=19)
    porcentaje = db.Column(db.Float, nullable=True)  # compatibilidad con la versión anterior
    monto = db.Column(db.Float, default=0)  # total calculado al guardar
    moneda = db.Column(db.String(3), default="COP")
    concepto = db.Column(db.String(300), default="")
    estado = db.Column(db.String(20), default="pendiente")
    fecha_pago = db.Column(db.Date, nullable=True)
    notas = db.Column(db.Text, default="")
    creado = db.Column(db.DateTime, default=datetime.now)

    cliente = db.relationship("Cliente", back_populates="anticipos")
    cotizacion = db.relationship("Cotizacion", back_populates="anticipos")
    items = db.relationship(
        "ItemAnticipo", back_populates="anticipo", cascade="all, delete-orphan", order_by="ItemAnticipo.orden"
    )

    @property
    def cif(self):
        return round((self.fob or 0) + (self.flete or 0) + (self.seguro or 0) + (self.otros_cif or 0), 2)

    @property
    def base_gravable(self):
        return round(self.cif * (self.trm or 0))

    @property
    def arancel(self):
        return round(self.base_gravable * (self.arancel_pct or 0) / 100)

    @property
    def base_iva(self):
        return self.base_gravable + self.arancel

    @property
    def iva_tributo(self):
        return round(self.base_iva * (self.iva_tributo_pct or 0) / 100)

    @property
    def tributos(self):
        return self.arancel + self.iva_tributo

    @property
    def incluye_tributos(self):
        return self.cif > 0 and (self.trm or 0) > 0

    @property
    def total_conceptos(self):
        return round(sum(i.valor or 0 for i in self.items), 2)

    @property
    def total(self):
        return round(self.tributos + self.total_conceptos, 2)

    @property
    def grupos(self):
        """[(grupo, [items], subtotal)] en el orden estándar."""
        salida = []
        orden = GRUPOS_ANTICIPO + sorted({i.grupo for i in self.items} - set(GRUPOS_ANTICIPO))
        for grupo in orden:
            items = [i for i in self.items if i.grupo == grupo]
            if items:
                salida.append((grupo, items, round(sum(i.valor or 0 for i in items), 2)))
        return salida

    @property
    def vencido(self):
        return self.estado in ("pendiente", "enviada") and self.fecha_limite and self.fecha_limite < date.today()


class ItemAnticipo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    anticipo_id = db.Column(db.Integer, db.ForeignKey("anticipo.id"), nullable=False)
    grupo = db.Column(db.String(40), default="Otros gastos")
    orden = db.Column(db.Integer, default=0)
    descripcion = db.Column(db.String(300), nullable=False)
    valor = db.Column(db.Float, default=0)

    anticipo = db.relationship("Anticipo", back_populates="items")


class Correo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"), nullable=True)
    tipo = db.Column(db.String(20), default="libre")  # cotizacion | anticipo | cumpleanos | libre
    para = db.Column(db.String(300), default="")
    cc = db.Column(db.String(300), default="")
    asunto = db.Column(db.String(250), default="")
    cuerpo = db.Column(db.Text, default="")
    adjunto_tipo = db.Column(db.String(20), nullable=True)
    adjunto_id = db.Column(db.Integer, nullable=True)
    estado = db.Column(db.String(20), default="borrador")  # borrador | enviado | error
    error = db.Column(db.Text, default="")
    creado = db.Column(db.DateTime, default=datetime.now)
    enviado_en = db.Column(db.DateTime, nullable=True)

    cliente = db.relationship("Cliente", back_populates="correos")

    @property
    def adjunto(self):
        if self.adjunto_tipo == "cotizacion":
            return db.session.get(Cotizacion, self.adjunto_id)
        if self.adjunto_tipo == "anticipo":
            return db.session.get(Anticipo, self.adjunto_id)
        return None


def siguiente_numero(modelo, prefijo):
    anio = date.today().year
    base = f"{prefijo}-{anio}-"
    ultimo = modelo.query.filter(modelo.numero.like(f"{base}%")).order_by(modelo.numero.desc()).first()
    consecutivo = int(ultimo.numero.rsplit("-", 1)[1]) + 1 if ultimo else 1
    return f"{base}{consecutivo:04d}"


# ---------------------------------------------------------------------------
# Datos iniciales (tomados de los formatos de AMG Logistics)
# ---------------------------------------------------------------------------
IA, PU, OG = GRUPOS_ANTICIPO
# (nombre, unidad, aplica IVA, grupo en la solicitud de fondos)
CATALOGO_INICIAL = [
    ("Agenciamiento aéreo CIF 0,35% mín. 650.000", "Trámite", True, IA),
    ("Agenciamiento marítimo CIF 0,35% mín. 850.000", "Trámite", True, IA),
    ("Proceso de aduana aérea", "Trámite", True, IA),
    ("Proceso de aduana marítima", "Trámite", True, IA),
    ("Reconocimiento de la mercancía", "Servicio", True, IA),
    ("Elaboración declaración de importación (valor c/u)", "Unidad", True, IA),
    ("Elaboración certificados de origen", "Unidad", True, IA),
    ("Elaboración criterios de origen", "Unidad", True, IA),
    ("Documentación y fotocopias", "Servicio", True, IA),
    ("Gastos consolidados", "Servicio", False, IA),
    ("Descargue directo", "Servicio", False, IA),
    ("Desconsolidación 2,5% kg", "Kg", False, IA),
    ("Licencia de importación", "Trámite", False, IA),
    ("Vistos buenos otras dependencias", "Trámite", False, IA),
    ("Registro", "Trámite", False, IA),
    ("Formularios", "Unidad", False, IA),
    ("Creación clientes VUCE", "Trámite", True, IA),
    ("Flete aéreo", "Kg", False, PU),
    ("Flete marítimo", "Contenedor", False, PU),
    ("Flete terrestre", "Viaje", False, PU),
    ("Inland", "Viaje", False, PU),
    ("Cargue y descargue", "Servicio", False, PU),
    ("Liberación", "Servicio", False, PU),
    ("Manejo + liberación naviera", "Servicio", False, PU),
    ("Manejo aerolínea 6% kg", "Kg", False, PU),
    ("Manejos en puerto", "Servicio", False, PU),
    ("Gastos portuarios", "Servicio", False, PU),
    ("Gastos naviera", "Servicio", False, PU),
    ("Gastos en origen", "Servicio", False, PU),
    ("Gastos en destino", "Servicio", False, PU),
    ("Gastos operativos Cartagena", "Servicio", False, PU),
    ("Handling", "Servicio", False, PU),
    ("Bodegajes", "Día", False, PU),
    ("Depósito aduanero autorizado", "Día", False, PU),
    ("Depósito contenedor", "Día", False, PU),
    ("Traslado a depósito", "Viaje", False, PU),
    ("Uso instalaciones", "Servicio", False, PU),
    ("Día adicional en destino", "Día", False, PU),
    ("Emisión BL", "Unidad", False, PU),
    ("ENS + ACD", "Servicio", False, PU),
    ("Revisión antinarcóticos", "Servicio", False, PU),
    ("Entrega POD Manzanillo – Panamá", "Servicio", False, PU),
    ("Manejos DAP Panamá", "Servicio", False, PU),
    ("Póliza de seguro", "Servicio", False, OG),
    ("Logística y coordinación", "Servicio", True, OG),
    ("Movimientos bancarios", "Servicio", False, OG),
    ("Movimientos", "Servicio", False, OG),
    ("Endoso", "Servicio", False, OG),
    ("Papelería", "Servicio", False, OG),
    ("Etiquetado termofijado", "Unidad", True, OG),
    ("Tributos aduaneros DIAN", "Servicio", False, OG),
    ("Sanciones", "Servicio", False, OG),
]

DATOS_EMPRESA = {
    "nombre": "AMG LOGISTICS SAS",
    "nit": "901100033-0",
    "web": "https://amglogisticsco.com/",
    "direccion": "Transversal 42 No. 3-14 Piso 1",
    "ciudad": "Bogotá D.C.",
    "telefono": "+57 310 800 0481",
    "email": "info@amglogisticsco.com",
    "eslogan": "Soluciones integrales de transporte y logística",
    "datos_bancarios": "Cuenta de ahorros Davivienda N.º 108900181331\nA nombre de AMG LOGISTICS SAS",
    "pie_anticipo": "En el momento de realizar la transferencia, favor comunicarse con nosotros "
                    "para suministrarle el tipo de cambio del día.",
}

CONDICIONES_INICIALES = (
    "Esta cotización está sujeta a disponibilidad y confirmación de los proveedores al momento de la aceptación.\n"
    "Las tarifas de fletes internacionales pueden estar sujetas a cambios por parte de las navieras, aerolíneas o proveedores.\n"
    "Los tiempos de tránsito son estimados y pueden variar por condiciones operativas, climáticas o aduaneras.\n"
    "Los servicios no incluidos en esta cotización serán cotizados por separado.\n"
    "Gastos, impuestos, aranceles, bodegajes, demoras, inspecciones u otros conceptos no especificados serán asumidos según corresponda.\n"
    "Se tomará el mayor peso entre el peso físico y el peso volumétrico; cualquier fracción de kg se aproximará.\n"
    "Sujeta a cambios según peso físico, peso volumétrico, tipo de servicio, fecha del envío, origen, destino y tasa de cambio (TRM). "
    "El porcentaje del cargo por combustible varía cada mes.\n"
    "El cliente es responsable de diligenciar en la guía de transporte la descripción y posición arancelaria de la mercancía.\n"
    "Pueden causarse cargos adicionales si el origen o destino es considerado área remota; se liquidarán en destino.\n"
    "Las exportaciones con valor declarado superior a USD 5.000 requieren proceso de exportación ordinaria con agente de aduanas, "
    "con costos adicionales no incluidos.\n"
    "Las tarifas no incluyen costos de aduana, liberación o impuestos en destino en caso de presentarse."
)

NOTA_TARIFAS = (
    "Las tarifas NO incluyen IVA. Nuestros servicios están gravados con IVA del 19% y los pagos a terceros "
    "con el gravamen a movimientos financieros del 4x1000."
)

CUMPLE_ASUNTO = "¡Feliz cumpleaños, {nombre}!"
CUMPLE_MENSAJE = (
    "Estimado(a) {nombre}:\n\n"
    "En nombre de todo el equipo de {empresa}, le deseamos un muy feliz cumpleaños. "
    "Que este nuevo año esté lleno de salud, éxitos y grandes logros.\n\n"
    "Gracias por su confianza. Es un gusto acompañarle en cada operación.\n\n"
    "Cordial saludo,"
)

LOGO_INICIAL = Path(__file__).parent / "static" / "marca" / "logo.png"


def asegurar_columnas():
    """Agrega a SQLite las columnas nuevas de los modelos (migración simple, sin borrar datos)."""
    inspector = inspect(db.engine)
    for tabla in db.metadata.sorted_tables:
        if not inspector.has_table(tabla.name):
            continue
        existentes = {c["name"] for c in inspector.get_columns(tabla.name)}
        for columna in tabla.columns:
            if columna.name in existentes:
                continue
            tipo = columna.type.compile(db.engine.dialect)
            defecto = ""
            if columna.default is not None and columna.default.is_scalar:
                valor = columna.default.arg
                valor = int(valor) if isinstance(valor, bool) else valor
                defecto = f" DEFAULT {valor!r}" if isinstance(valor, str) else f" DEFAULT {valor}"
            with db.engine.begin() as conexion:
                conexion.execute(text(f'ALTER TABLE "{tabla.name}" ADD COLUMN "{columna.name}" {tipo}{defecto}'))


def sembrar_datos():
    # Si hay usuarios pero ningún administrador (bases anteriores), el primero pasa a serlo.
    if Usuario.query.count() and not Usuario.query.filter_by(rol="admin").count():
        Usuario.query.order_by(Usuario.id).first().rol = "admin"
    empresa = Empresa.actual()
    if not empresa.direccion and not empresa.nit:
        for campo, valor in DATOS_EMPRESA.items():
            if campo == "nombre" and empresa.nombre not in ("", "Mi Empresa"):
                continue
            setattr(empresa, campo, valor)
    for campo, valor in (("condiciones", CONDICIONES_INICIALES), ("nota_tarifas", NOTA_TARIFAS),
                         ("cumple_asunto", CUMPLE_ASUNTO), ("cumple_mensaje", CUMPLE_MENSAJE)):
        if not getattr(empresa, campo):
            setattr(empresa, campo, valor)
    if not empresa.logo and LOGO_INICIAL.exists():
        destino = Path(current_app.config["UPLOAD_DIR"]) / "logo.png"
        shutil.copyfile(LOGO_INICIAL, destino)
        empresa.logo = "logo.png"
    if Servicio.query.count() == 0:
        for nombre, unidad, iva, grupo in CATALOGO_INICIAL:
            db.session.add(Servicio(nombre=nombre, unidad=unidad, aplica_iva=iva, grupo=grupo))
    db.session.commit()
