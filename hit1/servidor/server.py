from flask import Flask, request, jsonify
import docker
from docker.errors import ImageNotFound, APIError
import requests
import time
import os
import subprocess

app = Flask(__name__)


def get_host_ip():
    try:
        resultado = (
            subprocess.check_output(  # subprocess directo, NO asyncio.subprocess
                ["ip", "route", "show", "default"], text=True
            )
        )
        ip = resultado.split()[2]
        print(f"[DEBUG] Host IP detectada: {ip}")
        return ip
    except Exception as e:
        print(f"[DEBUG] Falló detección de IP: {e}, usando fallback 172.17.0.1")
        return "172.17.0.1"  # IP del gateway Docker en Linux


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

    # PULL
    try:
        cliente.images.pull(imagen)
    except ImageNotFound:
        return jsonify({"error": "Imagen no encontrada"}), 404

    # RUN
    try:
        puerto_host = 5001  # ← movido antes de usarse
        host_ip = get_host_ip()  # ← obtener IP del host
        url_tarea = f"http://{host_ip}:{puerto_host}/ejecutarTarea"
        print(f"[DEBUG] URL del servicio tarea: {url_tarea}")

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
                    container.stop()
                except:
                    pass

    except APIError as e:
        print("Error al ejecutar el contenedor")
        return jsonify({"error": "Error de Docker API", "msg": str(e)}), 500

    return jsonify(datos_resultado), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
