import argparse
import csv
import os ## os es una libreria de Python que interactua con el sistema operativo 
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests


SERVER_BASE = "http://localhost:8080"
POST_URL = f"{SERVER_BASE}/ejecutarTareaRemota"
GET_URL_TEMPLATE = f"{SERVER_BASE}/consulta_tarea/{{}}"
HEALTH_URL = f"{SERVER_BASE}/estado"


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


def wait_server_ready(timeout_sec=30):##envia gets al servidor hasta que devuelva un status_code = 200
    ##esto se hace para esperar a que el servidor empiece a escuchar antes de enviar la tarea
    start = time.perf_counter()
    while time.perf_counter() - start < timeout_sec:
        try:
            r = requests.get(HEALTH_URL, timeout=2)
            if r.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


def post_task(i):##envia una sola tarea al servidor y devuelve el id
    payload = make_payload(i)
    r = requests.post(POST_URL, json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data["id_tarea"]


def poll_until_done(task_id, max_wait_sec=180):##consulta por el estado de su tarea hasta que 
    ##el estado de la misma sea distinto de pendiente
    start = time.perf_counter()
    while time.perf_counter() - start < max_wait_sec:
        r = requests.get(GET_URL_TEMPLATE.format(task_id), timeout=5)
        r.raise_for_status()
        data = r.json()
        if data.get("estado") != "pendiente":
            return data
        time.sleep(0.3)
    raise TimeoutError(f"Timeout esperando tarea {task_id}")##si tarda mas de 180 segundos a
##que el estado de la consulta cambie a pendiente, lanza timeout


def run_load(total_tasks, post_concurrency):##total_tasks es la cantidad de tareas que se van a 
    #ejecutar para la medicion del troughput, post_concurrency es cuantos hilos clientes de 
    #este programa van a hacer las consultas en simultaneo.
    # esta funcion es la que calcula el throughput
    
    task_ids = []##lista donde se van a guardar los ids de las tareas
    start = time.perf_counter()##se guarda el instante exacto de tiempo al comenzar la prueba

    with ThreadPoolExecutor(max_workers=post_concurrency) as executor:##se crea un objeto del 
        #tipo "pool de hilos" y se guarda su valor en la variable "executor"
        futures = []
        for i in range(total_tasks):
            futures.append(executor.submit(post_task, i))##executor.submit recibe la funcion a 
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
            futures.append(executor.submit(poll_until_done, task_id))
        for future in as_completed(futures):
            resultado = future.result()
            print(resultado)

    end = time.perf_counter()
    duration_sec = end - start
    throughput = total_tasks / (duration_sec / 60.0)##tareas por minuto 
    return duration_sec, throughput


def start_server(server_dir, workers):##crea un proceso hijo que se encarga de levantar el Server.py
    ##server_dir es la carpeta donde se encuentra Server.py y workers es la cantidad de workers que 
    #va a tener Server.py para atender las consultas
    env = os.environ.copy()##obtiene una copia de las variables de entorno del proceso actual
    env["WORKERS"] = str(workers)##a la variable de entorno "WORKERS" le asigna la cantidad
    #de workers que va a usar el servidor http en string, ya que las variables de entrono son
    #siempre en string, usan el formato clave-valor
    process = subprocess.Popen( ##crea un proceso hijo sin bloquear al padre
        [sys.executable, "Server.py"],##el proceso hijo ejecuta Server.py
        cwd=str(server_dir),##le dice al proceso hijo en que carpeta trabajo (donde se encuentra server.py)
        env=env,##le asigna el entorno del padre modificado (la variable WORKER modificada) 
        stdout=subprocess.DEVNULL,#redirige la salida estandar y los errores a nada, es decir, 
        stderr=subprocess.DEVNULL,#no se muestra nada. Para que se vean solo los datos de medicion
    )
    if not wait_server_ready(timeout_sec=45):
        process.terminate()
        raise RuntimeError("No se pudo iniciar el servidor para benchmark")
    return process


def stop_server(process):
    if process is None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()


def ascii_chart(rows):
    max_th = max(row["throughput_tpm"] for row in rows) if rows else 1
    lines = ["Curva de escalabilidad (ASCII)"]
    for row in rows:
        workers = row["workers"]
        throughput = row["throughput_tpm"]
        bar_len = int((throughput / max_th) * 40)
        lines.append(f"{workers:>2} workers | {'#' * bar_len} {throughput:.2f} tareas/min")
    return "\n".join(lines)


def write_results(output_dir, rows):
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "throughput_resultados.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "workers",
                "tasks",
                "repeats",
                "duracion_promedio_seg",
                "throughput_tpm",
                "speedup",
                "eficiencia",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    md_path = output_dir / "throughput_resultados.md"
    with md_path.open("w", encoding="utf-8") as f:
        f.write("# Resultados throughput\n\n")
        f.write("| workers | tasks | repeats | duracion promedio seg | throughput tpm | speedup | eficiencia |\n")
        f.write("|---:|---:|---:|---:|---:|---:|---:|\n")
        for row in rows:
            f.write(
                f"| {row['workers']} | {row['tasks']} | {row['repeats']} | {row['duracion_promedio_seg']:.2f} | "
                f"{row['throughput_tpm']:.2f} | {row['speedup']:.2f} | {row['eficiencia']:.2f} |\n"
            )

    chart_path = output_dir / "throughput_escalabilidad.txt"
    chart_path.write_text(ascii_chart(rows), encoding="utf-8")


def run_benchmark(server_dir, workers_list, tasks, repeats, post_concurrency):
    rows = []
    baseline = None

    for workers in workers_list:
        duraciones = []
        throughputs = []

        server_proc = None
        try:
            server_proc = start_server(server_dir, workers)
            # Calentamiento corto para estabilizar arranque de imagenes.
            _ = run_load(total_tasks=min(5, tasks), post_concurrency=min(post_concurrency, 5))

            for _ in range(repeats):
                dur, th = run_load(total_tasks=tasks, post_concurrency=post_concurrency)
                duraciones.append(dur)
                throughputs.append(th)
        finally:
            stop_server(server_proc)

        duracion_promedio = sum(duraciones) / len(duraciones)
        throughput_promedio = sum(throughputs) / len(throughputs)

        if baseline is None:
            baseline = throughput_promedio

        speedup = throughput_promedio / baseline if baseline else 0.0
        eficiencia = speedup / workers if workers else 0.0

        rows.append(
            {
                "workers": workers,
                "tasks": tasks,
                "repeats": repeats,
                "duracion_promedio_seg": duracion_promedio,
                "throughput_tpm": throughput_promedio,
                "speedup": speedup,
                "eficiencia": eficiencia,
            }
        )

    return rows


def main():
    parser = argparse.ArgumentParser(description="Benchmark de throughput para hit2/servidor")
    parser.add_argument("--tasks", type=int, default=40, help="cantidad de tareas por corrida")
    parser.add_argument("--repeats", type=int, default=3, help="cantidad de repeticiones por worker")
    parser.add_argument(
        "--workers",
        type=int,
        nargs="+",
        default=[1, 2, 4, 8],
        help="lista de workers a medir",
    )
    parser.add_argument(
        "--post-concurrency",
        type=int,
        default=20,
        help="concurrencia de envio y polling en cliente benchmark",
    )
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    server_dir = base_dir / "servidor"
    output_dir = base_dir / "resultados"

    rows = run_benchmark(
        server_dir=server_dir,
        workers_list=args.workers,
        tasks=args.tasks,
        repeats=args.repeats,
        post_concurrency=args.post_concurrency,
    )
    write_results(output_dir, rows)

    print("Benchmark finalizado")
    for row in rows:
        print(
            f"workers={row['workers']} throughput={row['throughput_tpm']:.2f} tpm "
            f"speedup={row['speedup']:.2f} eficiencia={row['eficiencia']:.2f}"
        )
    print(f"Resultados en: {output_dir}")


if __name__ == "__main__":
    main()
