# Gestor Comercial

Aplicación web para gestionar clientes, cotizaciones, solicitudes de anticipo y correos, con saludos de cumpleaños automáticos. Está pensada para una empresa de logística y comercio exterior.

![Panel](ejemplos/panel.png)

## Qué incluye

| Módulo | Qué hace |
|---|---|
| **Clientes** | Base de datos con NIT, contacto, correos en copia, teléfono, dirección, notas y fecha de nacimiento (opcional). Se puede buscar, importar y exportar en CSV (Excel). |
| **Servicios y tarifas** | Catálogo precargado: documentación de importación/exportación, agenciamiento aduanero, reconocimiento previo, etiquetado, alistamiento, almacenaje, transporte de carga y fletes internacionales. Cada servicio tiene unidad, tarifa e IVA. |
| **Cotizaciones** | Numeración automática (`COT-2026-0001`), datos de la operación (tipo, modalidad, Incoterm, ruta, mercancía, peso y volumen), ítems del catálogo o libres, IVA por línea y PDF profesional. Estados: borrador, enviada, aprobada, rechazada y vencida. |
| **Anticipos** | Se generan desde una cotización aprobada con el porcentaje sugerido. Incluyen PDF con los datos bancarios y control de pago. |
| **Correos** | Borradores listos con el PDF adjunto. **Nada se envía sin tu revisión y confirmación.** Guarda el historial por cliente. |
| **Cumpleaños** | Cada día a las 8:00 (hora de Bogotá) prepara el saludo de quien cumple años. Por defecto queda como borrador; el envío automático se activa en Configuración. |
| **Panel** | Lo cotizado en el mes, cotizaciones aprobadas y en espera, anticipos por cobrar, correos pendientes y próximos cumpleaños. |

Ejemplos de documentos: [cotización](ejemplos/cotizacion-ejemplo.pdf) · [anticipo](ejemplos/anticipo-ejemplo.pdf)

## Instalación

Requisitos: Python 3.11 o superior. En Linux también hacen falta las librerías de WeasyPrint (`libpango`).

```bash
python -m venv .venv
source .venv/bin/activate        # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # y completa los valores
python run.py                    # abre http://localhost:5000
```

La primera vez, la app te pide crear tu usuario. Después ve a **Configuración** y completa los datos de la empresa: logo, NIT, datos bancarios y firma.

## Configurar el correo corporativo

En el archivo `.env`:

```ini
SMTP_MODO=smtp
SMTP_HOST=mail.tudominio.com
SMTP_PORT=587
SMTP_SEGURIDAD=tls
SMTP_USUARIO=comercial@tudominio.com
SMTP_CLAVE=tu-clave
SMTP_REMITENTE=comercial@tudominio.com
```

Mientras `SMTP_MODO=archivo`, los correos se guardan en `instance/correos_prueba/` y **no le llegan a nadie**. Así puedes probar sin riesgo.

| Proveedor | Servidor | Puerto / seguridad |
|---|---|---|
| Microsoft 365 / Outlook | `smtp.office365.com` | 587 / tls |
| Google Workspace | `smtp.gmail.com` | 587 / tls (usa una "contraseña de aplicación") |
| cPanel / hosting | `mail.tudominio.com` | 465 / ssl o 587 / tls |

## Publicarla en internet

Para usarla desde el celular o la oficina, súbela a un servidor como Render, Railway o una VPS. El comando de arranque es:

```bash
gunicorn -w 1 -b 0.0.0.0:$PORT run:app
```

Usa un solo *worker* (`-w 1`) para que la tarea de cumpleaños no se ejecute dos veces. Configura un `SECRET_KEY` fijo y haz copias de seguridad de `instance/gestor.db`.

## Pruebas

```bash
pip install pytest && python -m pytest
```

## Hoja de ruta recomendada

**Fase 2: agilidad comercial**
1. **Seguimiento automático:** un recordatorio (borrador) a los 3 días de enviar una cotización sin respuesta.
2. **Recordatorio de anticipos** antes y después de la fecha límite.
3. **Plantillas de cotización** por tipo de operación, por ejemplo "Importación marítima FCL", para cotizar en un clic.
4. **Envío por WhatsApp** del PDF con un enlace (wa.me).
5. **Varias monedas con TRM** del día para cotizaciones en USD.

**Fase 3: el agente con IA**
1. **Redactar correos** con Claude según el contexto del cliente y el historial.
2. **Cotizar desde un correo:** pegas la solicitud del cliente y el agente arma el borrador de la cotización.
3. **Resumen semanal:** qué cotizaciones seguir, quién no ha pagado y qué clientes no han vuelto a cotizar.
4. **Bandeja de entrada:** leer las respuestas de los clientes y marcar automáticamente las cotizaciones como aprobadas o rechazadas.

**Fase 4: operación y control**
- Usuarios con roles (comercial, financiero), facturación electrónica (DIAN) vía proveedor tecnológico, seguimiento de cada operación (estados del embarque) y reportes de ventas por cliente o servicio.
