FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir flask

COPY servicioTarea.py /app/servicioTarea.py

EXPOSE 5000

CMD ["python", "servicioTarea.py"]
