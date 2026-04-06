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
    print("'Status code':", response.status_code)
    print(response.text)
    if response.status_code==200:
        print("Resultado:", response.json())
        id_tarea= response.json().get("id_tarea")
        url=f"http://localhost:8080/consulta_tarea/{id_tarea}"
        respuesta2=requests.get(url)
        data = respuesta2.json()
        if data.get("estado")!="pendiente":
            print(f"'Status code':{respuesta2.status_code}")
            print(data)
        else:
            while data.get("estado")=="pendiente":
                url=f"http://localhost:8080/consulta_tarea/{id_tarea}"
                respuesta2=requests.get(url)
                data = respuesta2.json()
            print(f"'Status code':{respuesta2.status_code}")
            print(data)

enviar_request()



