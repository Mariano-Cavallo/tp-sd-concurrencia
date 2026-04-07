# Orquestador de Tareas con Docker

Sistema distribuido que permite ejecutar tareas de cómputo de forma remota mediante contenedores Docker efímeros. Un cliente envía una solicitud a un servidor orquestador, que levanta dinámicamente un contenedor para procesar la tarea y devuelve el resultado.

---

## Arquitectura

```
┌─────────────┐        HTTP POST          ┌──────────────────────┐
│             │  /ejecutarTareaRemota      │                      │
│  Cliente    │ ─────────────────────────▶│  Servidor            │
│ (Cliente.py)│                           │  Orquestador         │
│             │◀─────────────────────────│  (server.py :8080)   │
└─────────────┘     { resultado: X }      │                      │
                                          └──────────┬───────────┘
                                                     │
                                          docker.from_env()
                                          (vía Docker socket)
                                                     │
                                          ┌──────────▼───────────┐
                                          │  Contenedor efímero  │
                                          │  servicioTarea       │
                                          │  (:5000 → :5001)     │
                                          │                      │
                                          │  POST /ejecutarTarea │
                                          │  { suma | resta }    │
                                          └──────────────────────┘
                                          (se autodestruye al responder)
```

### Componentes

| Componente | Archivo | Puerto | Descripción |
|---|---|---|---|
| Cliente | `Cliente.py` | — | Interfaz de usuario por consola |
| Orquestador | `server.py` | 8080 | Gestiona el ciclo de vida de contenedores |
| Servicio Tarea | `servicioTarea.py` | 5000 (interno) / 5001 (host) | Ejecuta la tarea y termina |

---

## Instrucciones de ejecución

### Prerrequisitos

- Docker instalado y corriendo
- Python 3.11+
- Las imágenes publicadas en Docker Hub

### 1. Levantar el servidor orquestador

```bash
docker run --rm \
  --network mi-red \
    -p 8080:8080 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  marianocavallo/server:latest
```

> **¿Por qué `-v /var/run/docker.sock`?** El orquestador necesita comunicarse con el daemon de Docker del host para poder lanzar contenedores dinámicamente. Este montaje le da acceso al socket Unix de Docker.

### 2. Ejecutar el cliente

En otra terminal, con Python y la librería `requests` instalada:

```bash
pip install requests
python Cliente.py
```

El cliente te va a pedir:
1. La tarea a realizar (`suma` o `resta`)
2. Los valores de `a` y `b`

### 3. Verificar que el servidor está activo (opcional)

```bash
curl http://localhost:8080/estado
# → {"estado": "activo", "code": 200}
```

---

## CI/CD

El pipeline de GitHub Actions (`ci-cd.yml`) se ejecuta en cada push o pull request a `main` y realiza dos trabajos:

1. **Gitleaks**: escanea el historial de commits en busca de secrets hardcodeados (API keys, contraseñas, tokens). El build no continúa si se detecta alguno.

2. **Build y Push**: construye las imágenes Docker del servidor y del servicio tarea, y las publica en Docker Hub. El push a Docker Hub solo ocurre en merges a `main`, no en pull requests.

Los secrets `DOCKER_USERNAME` y `DOCKER_PASSWORD` deben estar configurados en el repositorio de GitHub.

---

## Decisiones de diseño

### Contenedores efímeros (self-destruct)
El `servicioTarea` se autodestruye después de responder usando `os._exit(0)` en el callback `call_on_close` de Flask. Esto garantiza que cada tarea corre en un entorno completamente limpio y aislado, sin estado residual entre ejecuciones. El flag `remove=True` en el orquestador complementa esto eliminando el contenedor del sistema una vez que termina.

### Docker-outside-of-Docker (DooD)
En lugar de instalar Docker dentro del contenedor del orquestador (Docker-in-Docker), se monta el socket del host (`/var/run/docker.sock`). Esto es más liviano y evita la complejidad de correr un daemon de Docker anidado. La contrapartida es que cualquier proceso con acceso a ese socket tiene control total sobre el Docker del host, por lo que en producción se debería restringir el acceso.

### Separación de responsabilidades
El cliente no sabe nada de Docker ni de cómo se ejecuta la tarea. Solo habla HTTP con el orquestador. El orquestador no sabe qué hace la tarea, solo sabe cómo lanzar contenedores y reenviar parámetros. El servicio tarea solo sabe resolver operaciones matemáticas.
