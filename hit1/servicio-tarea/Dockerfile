FROM python:3.11-slim

WORKDIR /app

COPY servicioTarea.py .

RUN pip install flask

EXPOSE 5000

CMD ["python", "servicioTarea.py"]