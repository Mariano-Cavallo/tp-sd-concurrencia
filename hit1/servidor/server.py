from asyncio import subprocess
from flask import Flask, request, jsonify
import docker
from docker.errors import ImageNotFound, APIError
import requests
import time
import os

app = Flask(__name__)


def get_host_ip():
    try:
        # Funciona en Linux
        resultado = subprocess.check_output(
            ["ip", "route", "show", "default"],
            text=True
        )
        return resultado.split()[2]  # extrae la IP del gateway
    except Exception:
        # Fallback para Docker Desktop (Windows/Mac)
        return "host.docker.internal"


@app.route("/estado", methods=["GET"])
def get_estado():
    return jsonify(
        {
            "estado": "activo",
            "code": 200,
        }
    )


@app.route("/ejecutarTareaRemota", methods=["POST"])
def ejecutarTareaRemota():
    data = request.get_json()
    imagen = data.get("imagen")
    # logica de chequeo de la imagen

    parametros = data.get("parametros")
    # logica de tarea valida

    host_ip = get_host_ip()
    url_tarea = f"http://{host_ip}:{puerto_host}/ejecutarTarea"

    # logica de autenticacion y autorizacion de docker creo que no es necesario
    try:
        cliente = docker.from_env()
    except docker.errors.DockerException as e:
        return jsonify({"error": "Error de conexión con Docker", "msg": str(e)}), 500

    # PULL
    try:
        cliente.images.pull(imagen)
    except ImageNotFound:
        return jsonify({"error": "Imagen no encontrada"}), 404

    #  RUN
    try:
        # ********* fijarse la ip y puerto del contenedor ******** a chequear!!!!!!!!!!!!
        puerto_host = 5001
        container = cliente.containers.run(
            imagen, detach=True, ports={"5000/tcp": puerto_host}, remove=True
        )

        time.sleep(2)


        try:
            respuesta_tarea = requests.post(url_tarea, json=parametros)
            datos_resultado = respuesta_tarea.json()
        except requests.exceptions.ConnectionError:
            print("Error de conexión al servicio de la tarea")
            return (
                jsonify({"error": "No se pudo conectar con el servicio de la tarea"}),
                500,
            )
        finally:
            if container:
                try:
                    # Si os._exit(0) ya actuó, stop() lanzará una excepción que ignoramos
                    container.stop()
                except:
                    pass

    except APIError as e:
        print("Error al ejecutar el contenedor")
        return jsonify({"error": "Error de Docker API", "msg": str(e)}), 500

    return jsonify(datos_resultado), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
