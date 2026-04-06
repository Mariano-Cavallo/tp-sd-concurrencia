import requests
import time

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
    print("'Status code':", response.status_code)
    print(response.text)
    if response.status_code == 200:
        post_data = response.json()
        print("Resultado:", post_data)

        id_tarea = post_data.get("id_tarea")
        url = f"http://localhost:8080/consulta_tarea/{id_tarea}"
        respuesta2 = requests.get(url)
        data = respuesta2.json()

        if data.get("estado") != "pendiente":
            print(f"'Status code':{respuesta2.status_code}")
            print(data)
        else:
            while data.get("estado") == "pendiente":
                time.sleep(0.5)
                url = f"http://localhost:8080/consulta_tarea/{id_tarea}"
                respuesta2 = requests.get(url)
                data = respuesta2.json()
            print(f"'Status code':{respuesta2.status_code}")
            print(data)

enviar_request()



