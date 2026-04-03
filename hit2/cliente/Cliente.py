import requests

SERVIDOR_URL = "http://localhost:8080/ejecutarTareaRemota"

payload = {
    "imagen": "marianocavallo/servicio-tarea:latest",
    "parametros": {
        "tarea": "suma",
        "a": 10,
        "b": 5,
    },
    "timeout": 15,
}


response = requests.post(SERVIDOR_URL, json=payload)

print("Status:", response.status_code)
print("Resultado:", response.json())
