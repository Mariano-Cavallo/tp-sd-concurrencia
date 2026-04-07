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

##la comunicacion de cliente Docker con servidor Docker, aunque es local, utiliza sockets
#siguien el modelo cliente-servidor aunque sea local 

def conectar_docker(max_intentos=10, delay=2):
    """
    Intenta conectarse al demonio Docker con reintentos.
    """
    global cliente
    for intento in range(1, max_intentos + 1):
        try:
            cliente = docker.from_env()##se crea un cliente Docker mediante las variables
            #obtenidas con from_env(), una de ellas es DOCKER_HOST que indica a que demonio conectarse, 
            #ejemplos de DOCKER_HOST:unix:///var/run/docker.sock (Linux)
            #npipe:////./pipe/docker_engine (Windows)
            #tcp://192.168.1.50:2376 (daemon remoto) 
            #Otra de las variables es DOCKER_TLS_VERIFY que indica si se debe usar TLS para la conexion
            #la otra es DOCKER_CERT_PATH que indica en que carpeta estan los certificados TLS
            #Es decir, la variable mas importante es DOCKER_HOST ya que las otras dos se tendrian 
            #en cuenta solo si DOCKER_HOST tiene el valor de un demonio remoto
            print(f"Conexion con Docker exitosa en intento {intento}")
            return cliente
        except docker.errors.DockerException as e:
            print(f"Intento {intento}/{max_intentos} fallido: {e}")
            if intento < max_intentos:
                print(f"Reintentando en {delay} segundos...")
                time.sleep(delay)

    raise Exception(f"No se pudo conectar a Docker despues de {max_intentos} intentos")


cliente = conectar_docker()

##se utiliza un mismo proceso para todos los contenedores que corran en la misma maquina, donde 
# va a tener un socket por cada contenedor que haya (para recibir peticiones y redirigirlas a
# los programas servidores).

def get_host_ip():## define la ip que va a esperar peticiones/paquetes el contenedor de servicio 
    # tarea en el sistema anfitrion (donde vive docker), es decir, el contenedor del server 
    # actuaria como un cliente "normal" (es el mismo funcionamiento en la interaccion 
    # cliente-servidor), el contenedor de servicio tarea, no tiene idea que la peticion que le
    # llega es de otro contenedor.
    # Permite override manual para forzar host desde variable de entorno, ya que esta variable 
    # de entorno es definida por el usuario, por ejemplo si yo hago en este mismo codigo,
    # antes de ejecutar esta funcion: os.getenv("DOCKER_HOST_GATEWAY")= 172.17.0.1 
    # me "ahorro" de hacer todo el bloque de codigo que esta debajo de host_override evitando
    # que el programa haga la autodeteccion de la ip (todo lo que esta abajo de host_override)
    
    # get_host_ip() se ejecuta unicamente en el caso de que el server.py no sea ejecutado desde
    # un contenedor

    host_override = os.getenv("DOCKER_HOST_GATEWAY")#lee la variable de entorno "DOCKER_HOST_GATEWAY"
    #perteneciente a este contenedor, tendria el valor del default gateway de la red de docker
    #que permite "salir" al sistema anfitrion
    if host_override:
        print(f"[DEBUG] Usando DOCKER_HOST_GATEWAY={host_override}")
        return host_override

    sistema = platform.system().lower()##se usa para detectar el SO actual de este proceso/programa
    # es decir, si estoy corriendo server.py en el contenedor (que usa linux) va a devolver linux
    # si server.py lo estoy ejecutando sin el contenedor (en mi sistema anfitrion) va a devolver
    # windows o el que sea

    if sistema == "windows" or sistema == "darwin":
        print("[DEBUG] Sistema Windows/Mac detectado, usando host.docker.internal")
        return "host.docker.internal" ##host.docker.internal equivale al defaulta gateway de la
        # red docker para acceder al sistema anfitrion, es decir seria como: "el sistema anfitrion
        # visto desde dentro del contenedor"

    try:##entra al bloque try si el S.O. no es ni windows ni mac 
        resultado = subprocess.check_output(["ip", "route", "show", "default"], text=True)##ejecuta el 
        ##comando ip route show default para obtener el default gateway de la red virtual de docker
        ip = resultado.split()[2] ##extrae la ip del default gateway
        print(f"[DEBUG] Host gateway detectado en Linux: {ip}")
        return ip
    except Exception as e:
        print(f"[DEBUG] Fallo deteccion Linux: {e}, usando fallback host.docker.internal")
        return "host.docker.internal"


def get_service_hosts():#funcion que devuelve una lista de ips candidatas
    hosts = []
    host_override = os.getenv("DOCKER_HOST_GATEWAY")
    if host_override:##si alguien definio la variable, la agrega a la lista
        hosts.append(host_override)

    if not os.path.exists("/.dockerenv"):##chequea si existe el archivo /.dockerenv que suele
        # existir dentro de un contenedor docker, si no existe, asume que esta corriendo fuera de un
        # contenedor (en el sistema anfitrion). Si esta corriendo en el sistema anfitrion, 
        # agrega "localhost" a la lista de direcciones posibles
        hosts.append("localhost")
        print("[DEBUG] Servidor en host, usando localhost")
    else:##si esta dentro del contenedor agrega "host.docker.internal" y trata de obtener 
        # una direccion posible con la funcion get_host_ip(), que seria la del default gateway 
        # la red docker
        hosts.append("host.docker.internal")
        hosts.append(get_host_ip())

    hosts_unicos = []
    for host in hosts:
        if host and host not in hosts_unicos:
            hosts_unicos.append(host)##agrega a la lista de ips unicas aquella que todavia no 
            # se incluyo, ya que puede haber ips repetidas (como "host.docker.internal")

    print(f"[DEBUG] Hosts candidatos para servicio tarea: {hosts_unicos}")
    return hosts_unicos


app = Flask(__name__)

# Estado compartido.
tareas_get = {}
tareas_lock = threading.Lock()

id_tarea = -1
id_tarea_lock = threading.Lock()

MAX_COLA_TAREAS = int(os.getenv("MAX_COLA_TAREAS", "1000"))##Se lee la variable de entorno 
#"MAX_COLA_TAREAS" de este proceso, si no tiene ningun valor, usa el valor por default (1000)
cantidad_workers = int(os.getenv("WORKERS", "3"))##Se lee la variable de entorno 
#"WORKERS" de este proceso, si no tiene ningun valor, usa el valor por default (3)

## se hizo de esta manera ya que se puede cambiar el comportamiento del servidor segun las 
# variables de entorno sin necesidad de tener que cambiar el codigo y, por lo tanto, tener 
# que hacer un rebuild de la imagen
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

        ##se obtienen las ips donde el proceso docker redirige las peticiones al contenedor
        # (donde se encuentra servicio-tarea)

        
        
        container = cliente.containers.run(imagen, detach=True, ports={"5000/tcp": None}, remove=True)
        ##corre el container. Detach=true -> el contenedor corre en segundo plano
        # remove=true cuando se detiene el contenedor, docker lo elimina automaticamente
        # ademas lo corre con el puerto donde va a escuchar peticiones el servidor flask de 
        # serivicio-tarea
        
        container.reload()##actualiza los datos del container (para que la instalacion
        # de las dependencias, por ejemplo, lleguen a actualizarse si es que no lo hicieron)

        puertos = container.attrs.get("NetworkSettings", {}).get("Ports", {}).get("5000/tcp")
        # Extrae el puerto donde va a capturar las peticiones el proceso docker para redirigirlas
        # al servidor flask dentro del contenedor

        #El funcionamiento es el siguiente:
           #1)El Flask de servicio-tarea escucha dentro del contenedor en 5000.
           #2)Docker publica ese 5000 en un puerto del sistema anfitrion.
           #3)El servidor llama al sistema anfitrion:HostPort, y Docker redirige al 5000 del 
           # contenedor.

        if not puertos:
            raise Exception("No se pudo mapear el puerto 5000/tcp del contenedor")

        puerto_host = puertos[0].get("HostPort") ##toma el primer puerto de la lista
        ultimo_error = None
        exito = False

        # Reintentos cortos mientras levanta Flask en el contenedor de tarea.
        for _ in range(12): ## el _ indica que el valor de la iteracion no se usa, solo importa repetir 12 veces
            for host in hosts_servicio:
                url_tarea = f"http://{host}:{puerto_host}/ejecutarTarea" 
                print(f"[DEBUG] URL del servicio tarea: {url_tarea}")
                try:
                    respuesta_tarea = requests.post(url_tarea, json=parametros, timeout=5)
                    respuesta_tarea.raise_for_status()##si el servicio-tarea devuelve codigo 400/500
                    #automaticamente se lanza la exception
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


def atender_tarea():
    while True:
        tarea_actual = cola_task.get()
        consultar_al_servicio(tarea_actual)
        


for i in range(cantidad_workers):
    worker = threading.Thread(target= atender_tarea, args=())
    worker.start()


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


@app.route("/estado", methods=["GET"])
def get_estado():
    return jsonify({"respuesta": "server activo", "workers": cantidad_workers}), 200


app.run(host="0.0.0.0", port=8080)