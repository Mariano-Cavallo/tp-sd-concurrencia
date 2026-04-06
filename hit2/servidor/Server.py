from flask import Flask, request, jsonify
import docker
from docker.errors import ImageNotFound, APIError
import requests
import time
import os
import subprocess
import threading
import traceback
from queue import Queue
import platform


def conectar_docker(max_intentos=10, delay=2):
    """
    Intenta conectarse al demonio Docker con reintentos.
    """
    global cliente
    for intento in range(1, max_intentos + 1):
        try:
            cliente = docker.from_env()
            print(f"Conexion con Docker exitosa en intento {intento}")
            return cliente
        except docker.errors.DockerException as e:
            print(f"Intento {intento}/{max_intentos} fallido: {e}")
            if intento < max_intentos:
                print(f"Reintentando en {delay} segundos...")
                time.sleep(delay)

    raise Exception(f"No se pudo conectar a Docker despues de {max_intentos} intentos")


cliente = conectar_docker()


def get_host_ip():
    # Permite override manual para forzar host desde variable de entorno.
    host_override = os.getenv("DOCKER_HOST_GATEWAY")
    if host_override:
        print(f"[DEBUG] Usando DOCKER_HOST_GATEWAY={host_override}")
        return host_override

    sistema = platform.system().lower()

    if sistema == "windows" or sistema == "darwin":
        print("[DEBUG] Sistema Windows/Mac detectado, usando host.docker.internal")
        return "host.docker.internal"

    try:
        resultado = subprocess.check_output(["ip", "route", "show", "default"], text=True)
        ip = resultado.split()[2]
        print(f"[DEBUG] Host gateway detectado en Linux: {ip}")
        return ip
    except Exception as e:
        print(f"[DEBUG] Fallo deteccion Linux: {e}, usando fallback host.docker.internal")
        return "host.docker.internal"


def get_service_hosts():
    hosts = []
    host_override = os.getenv("DOCKER_HOST_GATEWAY")
    if host_override:
        hosts.append(host_override)

    if not os.path.exists("/.dockerenv"):
        hosts.append("localhost")
        print("[DEBUG] Servidor en host, usando localhost")
    else:
        hosts.append("host.docker.internal")
        hosts.append(get_host_ip())

    hosts_unicos = []
    for host in hosts:
        if host and host not in hosts_unicos:
            hosts_unicos.append(host)

    print(f"[DEBUG] Hosts candidatos para servicio tarea: {hosts_unicos}")
    return hosts_unicos


app = Flask(__name__)

# Estado compartido.
tareas_get = {}
tareas_lock = threading.Lock()

id_tarea = -1
id_tarea_lock = threading.Lock()

MAX_COLA_TAREAS = int(os.getenv("MAX_COLA_TAREAS", "1000"))
cantidad_workers = int(os.getenv("WORKERS", "3"))

cola_task = Queue(maxsize=MAX_COLA_TAREAS)


def siguiente_id():
    global id_tarea
    with id_tarea_lock:
        id_tarea += 1
        return id_tarea


def crear_tarea_inicial(id_tarea_local, tarea_actual):
    with tareas_lock:
        tareas_get[id_tarea_local] = {
            "id_tarea": id_tarea_local,
            "estado": "pendiente",
            "resultado": None,
            "imagen": tarea_actual.get("imagen"),
            "parametros": tarea_actual.get("parametros"),
        }


def actualizar_tarea(id_tarea_local, estado, resultado=None):
    with tareas_lock:
        tarea = tareas_get.get(id_tarea_local)
        if tarea is None:
            return
        tarea["estado"] = estado
        tarea["resultado"] = resultado


def obtener_tarea(id_tarea_local):
    with tareas_lock:
        tarea = tareas_get.get(id_tarea_local)
        if tarea is None:
            return None
        return dict(tarea)


class Worker:
    def __init__(self, worker_id):
        self.worker_id = worker_id
        self.hilo_worker = threading.Thread(target=atender_tarea, args=(self,), daemon=True)


def consultar_al_servicio(tarea_actual):
    imagen = tarea_actual.get("imagen")
    id_tarea_local = tarea_actual.get("id_tarea")
    parametros = tarea_actual.get("parametros")

    if not imagen or parametros is None:
        actualizar_tarea(id_tarea_local, "request invalida", None)
        return

    try:
        cliente.images.pull(imagen)
    except ImageNotFound:
        actualizar_tarea(id_tarea_local, "Imagen Docker no encontrada", None)
        return

    container = None
    try:
        hosts_servicio = get_service_hosts()

        # Puerto dinamico para evitar conflictos entre workers concurrentes.
        container = cliente.containers.run(imagen, detach=True, ports={"5000/tcp": None}, remove=True)

        container.reload()
        puertos = container.attrs.get("NetworkSettings", {}).get("Ports", {}).get("5000/tcp")
        if not puertos:
            raise Exception("No se pudo mapear el puerto 5000/tcp del contenedor")

        puerto_host = puertos[0].get("HostPort")
        ultimo_error = None
        exito = False

        # Reintentos cortos mientras levanta Flask en el contenedor de tarea.
        for _ in range(12):
            for host in hosts_servicio:
                url_tarea = f"http://{host}:{puerto_host}/ejecutarTarea"
                print(f"[DEBUG] URL del servicio tarea: {url_tarea}")
                try:
                    respuesta_tarea = requests.post(url_tarea, json=parametros, timeout=5)
                    respuesta_tarea.raise_for_status()
                    datos_resultado = respuesta_tarea.json()
                    resultado = datos_resultado.get("resultado")
                    actualizar_tarea(id_tarea_local, "exito", resultado)
                    exito = True
                    break
                except requests.exceptions.RequestException as e:
                    ultimo_error = e
            if exito:
                break
            time.sleep(0.5)

        if not exito:
            print(f"[ERROR] Error al invocar servicio-tarea: {ultimo_error}")
            actualizar_tarea(id_tarea_local, "error al enviar la request", None)
    except APIError as e:
        print(f"[ERROR] APIError Docker: {e}")
        actualizar_tarea(id_tarea_local, "error al correr el contenedor Docker", None)
    except Exception as e:
        print(f"[ERROR] Excepcion no controlada en consultar_al_servicio: {e}")
        traceback.print_exc()
        actualizar_tarea(id_tarea_local, "error interno del servidor", None)
    finally:
        if container:
            try:
                container.stop()
            except Exception:
                pass


def atender_tarea(worker):
    while True:
        tarea_actual = cola_task.get()
        print(f"Worker {worker.worker_id} tomo tarea {tarea_actual.get('id_tarea')}")
        consultar_al_servicio(tarea_actual)
        cola_task.task_done()


for i in range(cantidad_workers):
    worker = Worker(i)
    worker.hilo_worker.start()


@app.route("/ejecutarTareaRemota", methods=["POST"])
def ejecutarTareaRemota():
    tarea_actual = request.get_json()
    if tarea_actual is None:
        return jsonify({"respuesta": "Error, el cuerpo debe ser JSON"}), 400

    id_tarea_local = siguiente_id()
    tarea_actual["id_tarea"] = id_tarea_local

    crear_tarea_inicial(id_tarea_local, tarea_actual)
    cola_task.put(tarea_actual)

    return jsonify({"respuesta": "tarea recibida", "id_tarea": id_tarea_local})


@app.route("/consulta_tarea/<int:idtarea>", methods=["GET"])
def get_consulta_tarea(idtarea):
    consulta = obtener_tarea(idtarea)
    if consulta is None:
        return jsonify({"respuesta": "Ocurrio un error desconocido, la tarea no se resolvio"}), 404

    return jsonify(consulta)