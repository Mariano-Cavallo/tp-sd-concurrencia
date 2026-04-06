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
    
    Args:
        max_intentos: número máximo de intentos
        delay: segundos de espera entre intentos
    
    Returns:
        cliente de Docker si logra conectarse
    
    Raises:
        Exception si no logra conectarse después de max_intentos
    """
    global cliente
    for intento in range(1, max_intentos + 1):
        try:
            cliente = docker.from_env()
            print(f"✓ Conexión con Docker exitosa en intento {intento}")
            return cliente
        except docker.errors.DockerException as e:
            print(f"✗ Intento {intento}/{max_intentos} fallido: {e}")
            if intento < max_intentos:
                print(f"  Reintentando en {delay} segundos...")
                time.sleep(delay)
    
    raise Exception(f"No se pudo conectar a Docker después de {max_intentos} intentos")


cliente=conectar_docker()

def get_host_ip():
    # Permite override manual si querés forzar host desde variable de entorno
    host_override = os.getenv("DOCKER_HOST_GATEWAY")
    if host_override:
        print(f"[DEBUG] Usando DOCKER_HOST_GATEWAY={host_override}")
        return host_override

    sistema = platform.system().lower()

    # En Docker Desktop (Windows/Mac), este hostname suele resolver al host
    if sistema == "windows" or sistema == "darwin":
        print("[DEBUG] Sistema Windows/Mac detectado, usando host.docker.internal")
        return "host.docker.internal"

    # Linux nativo: intenta detectar gateway por ruta default
    try:
        resultado = subprocess.check_output(
            ["ip", "route", "show", "default"], text=True
        )
        ip = resultado.split()[2]
        print(f"[DEBUG] Host gateway detectado en Linux: {ip}")
        return ip
    except Exception as e:
        print(f"[DEBUG] Falló detección Linux: {e}, usando fallback host.docker.internal")
        return "host.docker.internal"


def get_service_hosts():
    hosts = []
    host_override = os.getenv("DOCKER_HOST_GATEWAY")
    if host_override:
        hosts.append(host_override)

    # Si el servidor corre en el host, para llegar a un puerto publicado se usa localhost.
    if not os.path.exists("/.dockerenv"):
        hosts.append("localhost")
        print("[DEBUG] Servidor en host, usando localhost")
    else:
        # Dentro de contenedor: Docker Desktop suele exponer este alias al host.
        hosts.append("host.docker.internal")
        hosts.append(get_host_ip())

    # Elimina duplicados preservando orden.
    hosts_unicos = []
    for host in hosts:
        if host and host not in hosts_unicos:
            hosts_unicos.append(host)
    print(f"[DEBUG] Hosts candidatos para servicio tarea: {hosts_unicos}")
    return hosts_unicos

class Worker():
    def __init__(self):
        self.hilo_worker=threading.Thread(target=atender_tarea, args=(self,))
        self.ejecuta_task= threading.Event()
        self.tarea_actual=None ##El json de la request


def consultar_al_servicio(worker:Worker):
    imagen=worker.tarea_actual.get("imagen")
    id_tarea=worker.tarea_actual.get("id_tarea")
    try:
        cliente.images.pull(imagen)
        parametros=worker.tarea_actual.get("parametros")
    except ImageNotFound:
        tareas_get[id_tarea]={"estado": "Imagen Docker no encontrada", "resultado": None}
        ##Imagen no encontrada, cuando el cliente haga un get de la tarea le va a informar que la imagen no existe  
        return
        # RUN
    container = None
    try:
        hosts_servicio = get_service_hosts()

        # Puerto dinámico para evitar conflicto cuando hay varios workers en paralelo.
        container = cliente.containers.run(
            imagen, detach=True, ports={"5000/tcp": None}, remove=True
        )

        container.reload()
        puertos = container.attrs.get("NetworkSettings", {}).get("Ports", {}).get("5000/tcp")
        if not puertos:
            raise Exception("No se pudo mapear el puerto 5000/tcp del contenedor")

        puerto_host = puertos[0].get("HostPort")
        ultimo_error = None
        exito = False

        # Reintenta durante el arranque del servicio dentro del contenedor.
        for _ in range(12):
            for host in hosts_servicio:
                url_tarea = f"http://{host}:{puerto_host}/ejecutarTarea"
                print(f"[DEBUG] URL del servicio tarea: {url_tarea}")
                try:
                    respuesta_tarea = requests.post(url_tarea, json=parametros, timeout=5)
                    respuesta_tarea.raise_for_status()
                    datos_resultado = respuesta_tarea.json()
                    resultado = datos_resultado.get("resultado")
                    print(resultado)
                    tareas_get[id_tarea]={"estado":"exito", "resultado":resultado}
                    exito = True
                    break
                except requests.exceptions.RequestException as e:
                    ultimo_error = e
            if exito:
                break
            time.sleep(0.5)

        if not exito:
            print(f"[ERROR] Error al invocar servicio-tarea: {ultimo_error}")
            tareas_get[id_tarea]={"estado":"error al enviar la request", "resultado":None}
    except APIError as e:
        print(f"[ERROR] APIError Docker: {e}")
        tareas_get[id_tarea]={"estado":"error al correr el contenedor Docker", "resultado":None}
    except Exception as e:
        print(f"[ERROR] Excepcion no controlada en consultar_al_servicio: {e}")
        traceback.print_exc()
        tareas_get[id_tarea]={"estado":"error interno del servidor", "resultado":None}
    finally:##Este bloque se ejecuta si o si, haya tenido exito la request o no
        if container:
            try:
                container.stop()
            except:
                pass


def atender_tarea(worker:Worker):
    while True:
        worker.ejecuta_task.wait()##espera a recibir un "aviso" de que tiene que atender una tarea
        worker.ejecuta_task.clear()
        print("llego mi tarea a resolver")
        if worker.tarea_actual is not None:
            consultar_al_servicio(worker)
        
        while not cola_task.empty():
            worker.tarea_actual=cola_task.get()
            consultar_al_servicio(worker)
        worker.tarea_actual=None
        cola_workers_dispo.put(worker)

   


app = Flask(__name__)

cola_workers: Queue[Worker] = Queue(maxsize=3)
cola_workers_dispo:Queue[Worker] = Queue(maxsize=3)
cola_task = Queue(maxsize=10)##cambiar a tipo de dato request o json

cantidad_workers=3
for i in range(cantidad_workers):
    worker=Worker()
    cola_workers.put(worker)
    cola_workers_dispo.put(worker)
    worker.hilo_worker.start()

tareas_get={}

id_tarea = -1
id_tarea_lock = threading.Lock()
    
def siguiente_id():
    global id_tarea
    with id_tarea_lock:
        id_tarea += 1
    return id_tarea



@app.route("/ejecutarTareaRemota", methods=["POST"])
def ejecutarTareaRemota():
    if not cola_workers_dispo.empty():
        tarea_actual=request.get_json()##acordarse de limpiar este atributo en el hilo una vez terminada la ejecucion de la tarea
        if tarea_actual is None:
            return jsonify({"respuesta": "Error, el cuerpo debe ser JSON"}), 400
        worker=cola_workers_dispo.get()##saca el primer elemento que encuentra y lo elimina
        id_tarea=siguiente_id()
        tarea_actual["id_tarea"]=id_tarea
        worker.tarea_actual = tarea_actual
        payload = {"estado": "pendiente", "resultado": None}
        tareas_get[id_tarea] = payload
        worker.ejecuta_task.set()##activa al worker asignado
        return jsonify({"respuesta":"tarea recibida", "id_tarea":id_tarea })   
    else:
        tarea_actual=request.get_json()##acordarse de limpiar este atributo en el hilo una vez terminada la ejecucion de la tarea
        if tarea_actual is None:
            return jsonify({"respuesta": "Error, el cuerpo debe ser JSON"}), 400
        id_tarea=siguiente_id()
        print(f"tarea con id:{id_tarea} encolada, hay mas tareas que workers disponibles")
        tarea_actual["id_tarea"]=id_tarea
        payload = {"estado": "pendiente", "resultado": None}
        tareas_get[id_tarea] = payload
        cola_task.put(tarea_actual)
        return jsonify({"respuesta":"tarea recibida", "id_tarea":id_tarea })
    

@app.route("/consulta_tarea/<int:idtarea>", methods=["GET"]) 
def get_consulta_tarea(idtarea):
    consulta = tareas_get.get(idtarea)
    if consulta is None:
        return jsonify({"respuesta": "Ocurrio un error desconocido, la tarea no se resolvio"}), 404

    estado=consulta.get("estado")
    match estado:
        case "pendiente":
            return jsonify(consulta) 
            ##return jsonify({"respuesta":"La tarea aun no se resolvio, intentelo en un instante"}), 500
        case "Imagen Docker no encontrada":
            return jsonify(consulta)
            ##return jsonify({"respuesta":"La imagen Docker no esta disponible, la tarea no se resolvio"}), 400
        case "error al enviar la request":
            return jsonify(consulta)
            ##return jsonify({"respuesta":"Ocurrio un error al enviar la request, la tarea no se resolvio"}), 500
        case "error al correr el contenedor Docker":
            return jsonify(consulta)
            ##return jsonify({"respuesta":"Ocurrio un error al correr el contenedor Docker que resuelve la tarea, la tarea no se resolvio"}), 500 
        case "error interno del servidor":
            return jsonify(consulta)
        case "exito":
            return jsonify(consulta)
            ##return jsonify({"respuesta": f"La tarea fue resuelta exitosamente. Resultado: {consulta.get('resultado')}"}), 200
        case __case__:
            return jsonify(consulta)
            ##return jsonify({"respuesta": "Ocurrio un error desconocido, la tarea no se resolvio"}), 404

@app.route("/estado",methods=["GET"])
def get_estado():
    return jsonify({"respuesta": "server activo"}), 200


app.run(host="0.0.0.0", port=8080)