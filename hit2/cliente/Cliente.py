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

#localhost:8080 es el puerto donde el contenedor docker intercepta la solicitud al servidor htttp
#y la redirige hacia el servidor, no es el puerto donde realmente escucha el servidor flask
# el puerto donde intercepta las peticiones el proceso Docker cuando esta levantado el contenedor
# es, por ejemplo: docker run -p 9999:8080 servidor:latest, en este caso seria 9999 donde Docker intercepta
# las requests, por lo que la url a la cual se hace la request seria: SERVIDOR_URL = "http://localhost:9999/ejecutarTareaRemota"

#la response del servidor tambien pasa por el proceso Docker, por lo que el flujo para la request seria:
#cliente->docker (redirige conexion a puerto donde escucha el server flask)->server_flask
#para la response: server_flask->docker->cliente
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



