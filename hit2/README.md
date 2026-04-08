# Hit #2 - Concurrencia y Exclusion Mutua

Este hit extiende la solucion del Hit #1 para permitir multiples tareas concurrentes. El servidor recibe solicitudes de tareas remotas, las encola en una cola compartida y un pool de workers las ejecuta en paralelo levantando contenedores efimeros del servicio de tareas. De esta forma, el sistema desacopla la recepcion de solicitudes de su ejecucion efectiva, y evita condiciones de carrera al acceder a estructuras compartidas.

## Problema que se resuelve

Se busca resolver la ejecucion concurrente de tareas bajo estas condiciones:

1. Limitar la cantidad de ejecuciones simultaneas mediante un pool de workers configurable.
2. Encolar tareas cuando la demanda supera la cantidad de workers disponibles.
3. Garantizar exclusion mutua al manipular la cola y el estado de tareas compartido.
4. Medir throughput para distintas configuraciones de workers (1, 2, 4 y 8) y analizar escalabilidad.

Nota: en esta implementacion se resuelven el pool de workers, la cola con exclusion mutua y la medicion de throughput. Los relojes logicos de Lamport no fueron incorporados en el codigo actual.

## Arquitectura

```text
        HTTP POST /ejecutarTareaRemota
       +------------------------------------+
       |                                    v
       |                           +----------------------+
       | Cliente.py                | Servidor (Flask)     |
       | (sin contenedor)          | imagen: servidor     |
       |                           | puerto: 8080         |
       |  200 OK + { id_tarea }    | cola + N workers     |
       |<--------------------------+----------+-----------+
       |                                      |
       |  GET /consulta_tarea/{id}            | docker socket
       |  (polling hasta estado != pendiente) | (/var/run/docker.sock)
       +----------------------------+         v
                                    |  +----------------------+
                                    |  | Docker daemon (host) |
                                    |  +----------+-----------+
                                    |             |
                                    |             | run por tarea
                                    |             v
                                    |  +----------------------+
                                    |  | servicio-tarea       |
                                    |  | contenedor efimero   |
                                    |  | POST /ejecutarTarea  |
                                    |  +----------+-----------+
                                    |             |
                                    |             | resultado
                                    |             v
                                    +---- servidor actualiza
                                          estado de la tarea
```

Verificacion de salud:

```powershell
curl http://localhost:8080/estado
```

### 2) Ejecutar el cliente (sin contenedor)

Desde la raiz del repo:

```powershell
pip install requests
python .\hit2\cliente\Cliente.py
```

Importante: el payload del cliente debe apuntar a la imagen publica del servicio de tarea. Si corresponde, usar:

```text
valentinoaimale/servicio-tarea:latest
```

### 3) Detener el servidor

```powershell
docker stop servidor-hit2
```

## Prueba de throughput (contenedor throughput)

Para medir throughput, primero se levanta el servidor con la cantidad de workers deseada y luego se ejecuta el contenedor throughput.

### A) Levantar servidor para benchmarking

Ejemplo con 4 workers:

```powershell
docker run --rm -d `
	--name servidor-hit2 `
	--network bridge `
	-p 8080:8080 `
	-e WORKERS=4 `
	-e MAX_COLA_TAREAS=1000 `
	-v //var/run/docker.sock:/var/run/docker.sock `
	valentinoaimale/servidor:latest
```

### B) Ejecutar benchmark de throughput

```powershell
docker run --rm `
	--network bridge `
	-e SERVER_BASE=http://host.docker.internal:8080 `
	-e TASKS=40 `
	-e WORKERS=4 `
	-e POST_CONCURRENCY=20 `
	valentinoaimale/throughput:latest
```

Para repetir la medicion con 1, 2, 4 y 8 workers, cambiar WORKERS en el servidor y en el contenedor throughput para cada corrida.

### C) Variables de entorno relevantes

- Servidor:
	- WORKERS: cantidad de workers concurrentes.
	- MAX_COLA_TAREAS: capacidad maxima de la cola.
- Throughput:
	- SERVER_BASE: URL base del servidor.
	- TASKS: cantidad total de tareas a enviar.
	- WORKERS: valor informativo para etiquetar la corrida.
	- POST_CONCURRENCY: concurrencia del envio inicial de POST.

## Resultados de throughput y grafico

Tabla y grafico completos:

https://docs.google.com/spreadsheets/d/1hkKdafGoximoanS5B7FETscuCjH6rL6L1HakKUYCl2o/edit?usp=sharing

## Analisis breve de speedup

El speedup observado no es lineal porque, al aumentar workers, aparecen cuellos de botella compartidos que no escalan en la misma proporcion:

1. Docker daemon: todas las creaciones/paradas de contenedores pasan por el mismo daemon.
2. CPU del host: compite entre proceso del servidor, contenedores de servicio y cliente de carga.
3. I/O de imagenes y filesystem: creacion de contenedores y capas implica overhead fijo por tarea.
4. Red virtual de Docker: mayor trafico HTTP interno y NAT al aumentar concurrencia.
5. Secciones criticas en servidor: cola y estructuras compartidas con locks agregan espera bajo alta carga.

Por eso, aunque throughput mejora al subir workers, la ganancia marginal decrece y la curva se vuelve sublineal.

## Como identificar y medir cuellos de botella

1. CPU y memoria: docker stats y monitoreo del sistema operativo durante pruebas.
2. Overhead del daemon: tiempo de docker run/stop por tarea y latencia de arranque de contenedor.
3. Red Docker: latencia media y p95 de POST/GET, junto con errores/reintentos.
4. Cola del servidor: profundidad de cola y tiempo en estado pendiente por tarea.
5. Trazas de tiempo: timestamps en recepcion, inicio de ejecucion y finalizacion para separar espera vs procesamiento.
