# Usar una imagen base ligera de Python
FROM python:3.11-slim

# Establecer el directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema necesarias para algunas librerías de Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Copiar el archivo de requerimientos e instalar dependencias
# Se listan explícitamente para asegurar que docker-py esté presente
RUN pip install --no-cache-dir flask docker requests

# Copiar el código fuente del orquestador
COPY server.py .

# Exponer el puerto donde corre Flask (Orquestador)
EXPOSE 8080

# Definir la variable de entorno para que Flask no use buffer en los logs
ENV PYTHONUNBUFFERED=1

# Ejecutar la aplicación
CMD ["python", "server.py"]