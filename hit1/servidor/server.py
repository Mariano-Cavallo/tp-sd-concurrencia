from flask import Flask, request, jsonify
import docker
from docker.errors import ImageNotFound, APIError
import requests
import time

app = Flask(__name__)

NETWORK_NAME = "mi-red"
CONTAINER_NAME = "servicio-tarea"


def get_or_create_network(cliente):
    try:
        cliente.networks.get(NETWORK_NAME)
        print(f"[DEBUG] Red '{NETWORK_NAME}' ya existe")
    except docker.errors.NotFound:
        cliente.networks.create(NETWORK_NAME)
        print(f"[DEBUG] Red '{NETWORK_NAME}' creada")


@app.route("/estado", methods=["GET"])
def get_estado():
    return jsonify({"estado": "activo", "code": 200})


@app.route("/ejecutarTareaRemota", methods=["POST"])
def ejecutarTareaRemota():
    data = request.get_json()
    imagen = data.get("imagen")
    parametros = data.get("parametros")

    try:
        cliente = docker.from_env()
    except docker.errors.DockerException as e:
        return jsonify({"error": "Error de conexión con Docker", "msg": str(e)}), 500

    # Asegurar que la red existe
    get_or_create_network(cliente)

    # PULL
    try:
        cliente.images.pull(imagen)
    except ImageNotFound:
        return jsonify({"error": "Imagen no encontrada"}), 404

    # Limpiar contenedor anterior si quedó colgado
    try:
        old = cliente.containers.get(CONTAINER_NAME)
        old.remove(force=True)
        print(f"[DEBUG] Contenedor anterior '{CONTAINER_NAME}' eliminado")
    except docker.errors.NotFound:
        pass

    # RUN
    container = None
    try:
        url_tarea = f"http://{CONTAINER_NAME}:5000/ejecutarTarea"
        print(f"[DEBUG] URL del servicio tarea: {url_tarea}")

        container = cliente.containers.run(
            imagen,
            detach=True,
            name=CONTAINER_NAME,
            network=NETWORK_NAME,
            remove=True,
        )

        time.sleep(3)

        try:
            respuesta_tarea = requests.post(url_tarea, json=parametros)
            datos_resultado = respuesta_tarea.json()
        except requests.exceptions.ConnectionError:
            print("Error de conexión al servicio de la tarea")
            return jsonify({"error": "No se pudo conectar con el servicio de la tarea"}), 500
        finally:
            if container:
                try:
                    container.stop()
                except:
                    pass

    except APIError as e:
        print("Error al ejecutar el contenedor")
        return jsonify({"error": "Error de Docker API", "msg": str(e)}), 500

    return jsonify(datos_resultado), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
