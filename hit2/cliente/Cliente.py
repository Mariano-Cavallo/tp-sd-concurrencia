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


def enviar_request():
    response = requests.post(SERVIDOR_URL, json=payload)
    print("Status:", response.status_code)
    print(response.text)
    if response.status_code==200:
        print("Resultado:", response.json())
        id_tarea= response.json().get("id_tarea")
        url=f"http://localhost:8080/consulta_tarea/{id_tarea}"
        respuesta2=requests.get(url)
        print(f"'Estado':{respuesta2.status_code}")
        print(respuesta2.text)


enviar_request()



