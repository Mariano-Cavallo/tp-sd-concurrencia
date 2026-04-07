FROM python:3.11-slim

WORKDIR /app

COPY throughput.py /app/throughput.py

RUN pip install --no-cache-dir requests

ENTRYPOINT ["python", "throughput.py"]
