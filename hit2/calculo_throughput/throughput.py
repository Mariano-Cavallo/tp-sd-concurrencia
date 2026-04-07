import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


DEFAULT_SERVER_CANDIDATES = [
    "http://servidor:8080",
    "http://server:8080",
    "http://host.docker.internal:8080",
    "http://localhost:8080",
]


def build_urls(server_base):
    return {
        "post_url": f"{server_base}/ejecutarTareaRemota",
        "get_url_template": f"{server_base}/consulta_tarea/{{}}",
        "health_url": f"{server_base}/estado",
    }


def make_payload(i):##Genera el JSON de una tarea
    return {
        "imagen": "marianocavallo/servicio-tarea:latest",
        "parametros": {
            "tarea": "suma",
            "a": i,
            "b": i + 1,
        },
        "timeout": 15,
        "client_id": f"bench-{i}",
        "lamport_ts": i,
    }


def wait_server_ready(server_bases, timeout_sec=30):##envia gets al servidor hasta que devuelva un status_code = 200
    ##esto se hace para esperar a que el servidor empiece a escuchar antes de enviar la tarea
    start = time.perf_counter()##
    while time.perf_counter() - start < timeout_sec:
        for server_base in server_bases:
            health_url = build_urls(server_base)["health_url"]
            try:
                r = requests.get(health_url, timeout=2)
                if r.status_code == 200:
                    return server_base
            except requests.RequestException:
                pass
        time.sleep(0.5)
    return None


def post_task(i, post_url):##envia una sola tarea al servidor y devuelve el id
    payload = make_payload(i)
    r = requests.post(post_url, json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data["id_tarea"]


def poll_until_done(task_id, get_url_template, max_wait_sec=180):##consulta por el estado de su tarea hasta que 
    ##el estado de la misma sea distinto de pendiente
    start = time.perf_counter()
    while time.perf_counter() - start < max_wait_sec:
        r = requests.get(get_url_template.format(task_id), timeout=5)
        r.raise_for_status()
        data = r.json()
        if data.get("estado") != "pendiente":
            return data
        time.sleep(0.3)
    raise TimeoutError(f"Timeout esperando tarea {task_id}")##si tarda mas de 180 segundos a
##que el estado de la consulta cambie a pendiente, lanza timeout


def run_load(total_tasks, post_concurrency, post_url, get_url_template):##total_tasks es la cantidad de tareas que se van a 
    #ejecutar para la medicion del troughput, post_concurrency es cuantos hilos clientes de 
    #este programa van a hacer las consultas en simultaneo.
    # esta funcion es la que calcula el throughput
    
    task_ids = []##lista donde se van a guardar los ids de las tareas
    start = time.perf_counter()##se guarda el instante exacto de tiempo al comenzar la prueba

    with ThreadPoolExecutor(max_workers=post_concurrency) as executor:##se crea un objeto del 
        #tipo "pool de hilos" y se guarda su valor en la variable "executor"
        futures = []
        for i in range(total_tasks):
            futures.append(executor.submit(post_task, i, post_url))##executor.submit recibe la funcion a 
            ##ejecutar (post_task) y el argumento que recibe esa funcion (i) y devuelve un 
            # objeto de tipo Future, que indica que es algo que aun no tiene un resultado pero 
            # que lo va a tener. En este caso, el resultado que todavia no se obtuvo es la
            # respuesta del post al servidor. El objeto Future no proporciona paralelismo, eso
            # ya lo proporcionan los hilos del pool. Future da la posibilidad de tener un "estado"
            # de cada tarea/request, saber si termino, propagar exception si la request falla
        for future in as_completed(futures):##as_completed es una funcion de la libreria Future
            ##que recibe una lista de objetos de tipo Future acomoda los futures de manera tal 
            # que el primer Future que obtuvo el resultado es el primero de la lista y el 
            # ultimo Fututre que obtuvo el resultado es el ultimo de la misma. De esta manera,
            # se van guardando las requests que ya obtuvieron una respuesta y se le da tiempo a
            # las que todavia no obtuvieron la respuesta (ya que estan ultimas en la lista)
            # a que la obtengan. 
            task_ids.append(future.result())

    ##cuando sale del with se cierra el pool de hilos         

    with ThreadPoolExecutor(max_workers=post_concurrency) as executor:
        futures = []
        for task_id in task_ids:
            futures.append(executor.submit(poll_until_done, task_id, get_url_template))
        for future in as_completed(futures):
            resultado = future.result()
            

    end = time.perf_counter()
    duration_sec = end - start
    throughput = total_tasks / (duration_sec / 60.0)##tareas por minuto 
    return duration_sec, throughput


def run_benchmark(workers_list, tasks, post_concurrency, server_bases):
    rows = []

    active_server_base = wait_server_ready(server_bases=server_bases, timeout_sec=45)
    if not active_server_base:
        raise RuntimeError(
            f"No se pudo conectar al servidor. Bases probadas: {', '.join(server_bases)}"
        )

    urls = build_urls(active_server_base)
    print(f"Servidor detectado en: {active_server_base}")

    for workers in workers_list:
        _, throughput = run_load(
            total_tasks=tasks,
            post_concurrency=post_concurrency,
            post_url=urls["post_url"],
            get_url_template=urls["get_url_template"],
        )

        rows.append(
            {
                "workers": workers,
                "tasks": tasks,
                "throughput_tpm": throughput,
            }
        )

    return rows


def parse_workers_env(value):
    if not value:
        return [1, 2, 4, 8]
    normalized = value.replace(",", " ")
    tokens = normalized.split()
    if not tokens:
        return [1, 2, 4, 8]
    return [int(token) for token in tokens]


def main():
    default_tasks = int(os.getenv("TASKS", "40"))
    default_workers = parse_workers_env(os.getenv("WORKERS", "1 2 4 8"))
    default_post_concurrency = int(os.getenv("POST_CONCURRENCY", "20"))
    default_server_base = os.getenv("SERVER_BASE", "").strip()

    parser = argparse.ArgumentParser(description="Benchmark de throughput para hit2/servidor")
    parser.add_argument("--tasks", type=int, default=default_tasks, help="cantidad de tareas por corrida")
    parser.add_argument(
        "--workers",
        type=int,
        nargs="+",
        default=default_workers,
        help="lista de workers a medir",
    ) ## este parametro no hace nada, simplemente es para mostrar la cantidad de workers con 
    # la cual se hizo la prueba
    parser.add_argument(
        "--post-concurrency",
        type=int,
        default=default_post_concurrency,
        help="concurrencia de envio y polling en cliente benchmark",
    )
    parser.add_argument(
        "--server-base",
        type=str,
        default=default_server_base,
        help="URL base del servidor (ej: http://servidor:8080)",
    )
    args = parser.parse_args()

    if args.server_base:
        server_bases = [args.server_base]
    else:
        server_bases = DEFAULT_SERVER_CANDIDATES

    rows = run_benchmark(
        workers_list=args.workers,
        tasks=args.tasks,
        post_concurrency=args.post_concurrency,
        server_bases=server_bases,
    )

    print("Benchmark finalizado")
    for row in rows:
        print(f"workers={row['workers']} throughput={row['throughput_tpm']:.2f} tpm")


if __name__ == "__main__":
    main()
