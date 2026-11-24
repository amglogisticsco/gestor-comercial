from datetime import date, datetime, timedelta

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, login_manager

ESTADOS_COTIZACION = {
    "borrador": "Borrador",
    "enviada": "Enviada",
    "aprobada": "Aprobada",
    "rechazada": "Rechazada",
    "vencida": "Vencida",
}
ESTADOS_ANTICIPO = {"pendiente": "Pendiente", "enviada": "Enviada", "pagada": "Pagada", "anulada": "Anulada"}
TIPOS_OPERACION = ["Importación", "Exportación", "Nacional", "Otro"]
MODALIDADES = ["Marítima", "Aérea", "Terrestre", "Multimodal"]
INCOTERMS = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"]
MONEDAS = ["COP", "USD", "EUR"]


class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

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
    logo = db.Column(db.String(200), default="")
    color = db.Column(db.String(9), default="#12304F")
    moneda = db.Column(db.String(3), default="COP")
    iva_pct = db.Column(db.Float, default=19.0)
    validez_dias = db.Column(db.Integer, default=15)
    anticipo_pct = db.Column(db.Float, default=50.0)
    condiciones = db.Column(db.Text, default="")
    datos_bancarios = db.Column(db.Text, default="")
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
        return base.split()[0] if base else ""

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
    aplica_iva = db.Column(db.Boolean, default=True)
    activo = db.Column(db.Boolean, default=True)


class Cotizacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"), nullable=False)
    fecha = db.Column(db.Date, default=date.today)
    validez_dias = db.Column(db.Integer, default=15)
    estado = db.Column(db.String(20), default="borrador")
    tipo_operacion = db.Column(db.String(30), default="")
    modalidad = db.Column(db.String(30), default="")
    incoterm = db.Column(db.String(5), default="")
    origen = db.Column(db.String(120), default="")
    destino = db.Column(db.String(120), default="")
    mercancia = db.Column(db.String(200), default="")
    bultos = db.Column(db.String(40), default="")
    peso_kg = db.Column(db.String(40), default="")
    volumen_m3 = db.Column(db.String(40), default="")
    moneda = db.Column(db.String(3), default="COP")
    iva_pct = db.Column(db.Float, default=19.0)
    notas = db.Column(db.Text, default="")
    condiciones = db.Column(db.Text, default="")
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
        base = sum(i.total for i in self.items if i.aplica_iva)
        return round(base * (self.iva_pct or 0) / 100, 2)

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
    def tiene_operacion(self):
        return any([self.tipo_operacion, self.modalidad, self.origen, self.destino, self.mercancia, self.incoterm])

    @property
    def resumen(self):
        partes = []
        if self.tipo_operacion:
            partes.append(self.tipo_operacion.lower())
        if self.modalidad:
            partes.append(self.modalidad.lower())
        if self.origen and self.destino:
            partes.append(f"{self.origen} – {self.destino}")
        if partes:
            return "la operación de " + " ".join(partes)
        return "los servicios solicitados"


class ItemCotizacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cotizacion_id = db.Column(db.Integer, db.ForeignKey("cotizacion.id"), nullable=False)
    servicio_id = db.Column(db.Integer, db.ForeignKey("servicio.id"), nullable=True)
    orden = db.Column(db.Integer, default=0)
    descripcion = db.Column(db.String(300), nullable=False)
    cantidad = db.Column(db.Float, default=1)
    unidad = db.Column(db.String(40), default="Servicio")
    precio = db.Column(db.Float, default=0)
    aplica_iva = db.Column(db.Boolean, default=True)

    cotizacion = db.relationship("Cotizacion", back_populates="items")

    @property
    def total(self):
        return round((self.cantidad or 0) * (self.precio or 0), 2)


class Anticipo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"), nullable=False)
    cotizacion_id = db.Column(db.Integer, db.ForeignKey("cotizacion.id"), nullable=True)
    fecha = db.Column(db.Date, default=date.today)
    fecha_limite = db.Column(db.Date, nullable=True)
    porcentaje = db.Column(db.Float, nullable=True)
    monto = db.Column(db.Float, default=0)
    moneda = db.Column(db.String(3), default="COP")
    concepto = db.Column(db.String(300), default="")
    estado = db.Column(db.String(20), default="pendiente")
    fecha_pago = db.Column(db.Date, nullable=True)
    notas = db.Column(db.Text, default="")
    creado = db.Column(db.DateTime, default=datetime.now)

    cliente = db.relationship("Cliente", back_populates="anticipos")
    cotizacion = db.relationship("Cotizacion", back_populates="anticipos")

    @property
    def vencido(self):
        return self.estado in ("pendiente", "enviada") and self.fecha_limite and self.fecha_limite < date.today()


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


CATALOGO_INICIAL = [
    ("Documentación para importación", "Preparación y revisión de documentos de importación", "Trámite", True),
    ("Documentación para exportación", "Preparación y revisión de documentos de exportación", "Trámite", True),
    ("Agenciamiento aduanero", "Intermediación aduanera y gestión ante la autoridad", "Trámite", True),
    ("Reconocimiento previo de mercancía", "Inspección previa de la mercancía antes de la declaración", "Servicio", True),
    ("Etiquetado de mercancía", "Etiquetado conforme a la normativa aplicable", "Unidad", True),
    ("Alistamiento de mercancía", "Preparación, embalaje y consolidación de la carga", "Servicio", True),
    ("Almacenaje", "Almacenamiento de mercancía en bodega", "Día", True),
    ("Transporte de carga", "Transporte terrestre nacional de carga", "Viaje", True),
    ("Flete internacional marítimo", "Flete marítimo internacional", "Contenedor", False),
    ("Flete internacional aéreo", "Flete aéreo internacional", "Kg", False),
]

CONDICIONES_INICIALES = (
    "Precios expresados en la moneda indicada. No incluyen tributos aduaneros salvo que se indique.\n"
    "Tarifas sujetas a disponibilidad de espacio y equipo al momento de la reserva.\n"
    "Gastos no contemplados (bodegajes adicionales, inspecciones, demoras) se facturan según soporte."
)

CUMPLE_ASUNTO = "¡Feliz cumpleaños, {nombre}!"
CUMPLE_MENSAJE = (
    "Estimado(a) {nombre}:\n\n"
    "En nombre de todo el equipo de {empresa}, le deseamos un muy feliz cumpleaños. "
    "Que este nuevo año esté lleno de salud, éxitos y grandes logros.\n\n"
    "Gracias por su confianza. Es un gusto acompañarle en cada operación.\n\n"
    "Un cordial saludo,"
)


def sembrar_datos():
    empresa = Empresa.actual()
    if not empresa.condiciones:
        empresa.condiciones = CONDICIONES_INICIALES
    if not empresa.cumple_asunto:
        empresa.cumple_asunto = CUMPLE_ASUNTO
    if not empresa.cumple_mensaje:
        empresa.cumple_mensaje = CUMPLE_MENSAJE
    if Servicio.query.count() == 0:
        for nombre, descripcion, unidad, iva in CATALOGO_INICIAL:
            db.session.add(Servicio(nombre=nombre, descripcion=descripcion, unidad=unidad, aplica_iva=iva))
    db.session.commit()
