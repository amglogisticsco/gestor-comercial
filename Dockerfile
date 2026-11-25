FROM python:3.12-slim

# Librerías del sistema que WeasyPrint necesita para generar los PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 fonts-liberation tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Hora de Colombia para fechas de correos, cotizaciones y cumpleaños
ENV PYTHONUNBUFFERED=1 PORT=10000 TZ=America/Bogota
EXPOSE 10000
# Un solo worker para que la tarea diaria de cumpleaños no se ejecute dos veces
CMD gunicorn -w 1 --threads 4 -b 0.0.0.0:$PORT run:app
