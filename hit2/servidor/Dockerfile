FROM python:3.11-slim

WORKDIR /app

# Needed by get_host_ip() which uses: ip route show default
RUN apt-get update \
    && apt-get install -y --no-install-recommends iproute2 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir flask requests docker

COPY Server.py /app/Server.py

EXPOSE 8080

CMD ["python", "Server.py"]
