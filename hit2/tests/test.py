import subprocess
import time
import requests
import pytest

SERVIDOR_URL = "http://localhost:8080/ejecutarTareaRemota"
IMAGEN = "marianocavallo/servicio-tarea:latest"
NETWORK = "hit2-red"
CONTAINER_NAME = "servidor-test"


@pytest.fixture(scope="module")
def servidor():
    subprocess.run(
        ["docker", "network", "create", NETWORK],
        capture_output=True
    )

    subprocess.run([
        "docker", "run", "--rm",
        "-d",
        "--name", CONTAINER_NAME,
        "--network", NETWORK,
        "-p", "8080:8080",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "servidor"
    ], check=True)

    # Espera a que el servidor esté listo
    for _ in range(15):
        try:
            r = requests.get("http://localhost:8080/estado")
            if r.status_code == 200:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(2)
    else:
        pytest.fail("El servidor no levantó a tiempo")

    yield

    subprocess.run(["docker", "stop", CONTAINER_NAME], capture_output=True)
    subprocess.run(["docker", "network", "rm", NETWORK], capture_output=True)


def test_suma_async_e2e(servidor):
    payload = {
        "imagen": IMAGEN,
        "parametros": {
            "tarea": "suma",
            "a": 10,
            "b": 5
        }
    }

    # POST: el servidor responde inmediatamente con el id de la tarea
    respuesta = requests.post(SERVIDOR_URL, json=payload, timeout=10)
    assert respuesta.status_code == 200
    id_tarea = respuesta.json().get("id_tarea")
    assert id_tarea is not None

    # Polling hasta que la tarea termine
    data = {}
    for _ in range(60):
        consulta = requests.get(f"http://localhost:8080/consulta_tarea/{id_tarea}", timeout=5)
        assert consulta.status_code == 200
        data = consulta.json()
        if data.get("estado") != "pendiente":
            break
        time.sleep(1)
    else:
        pytest.fail("La tarea no terminó a tiempo")

    assert data.get("estado") == "exito"
    assert data.get("resultado") == 15


def test_resta_async_e2e(servidor):
    payload = {
        "imagen": IMAGEN,
        "parametros": {
            "tarea": "resta",
            "a": 10,
            "b": 3
        }
    }

    respuesta = requests.post(SERVIDOR_URL, json=payload, timeout=10)
    assert respuesta.status_code == 200
    id_tarea = respuesta.json().get("id_tarea")
    assert id_tarea is not None

    data = {}
    for _ in range(60):
        consulta = requests.get(f"http://localhost:8080/consulta_tarea/{id_tarea}", timeout=5)
        assert consulta.status_code == 200
        data = consulta.json()
        if data.get("estado") != "pendiente":
            break
        time.sleep(1)
    else:
        pytest.fail("La tarea no terminó a tiempo")

    assert data.get("estado") == "exito"
    assert data.get("resultado") == 7


def test_request_sin_imagen(servidor):
    payload = {
        "parametros": {"tarea": "suma", "a": 1, "b": 1}
    }

    respuesta = requests.post(SERVIDOR_URL, json=payload, timeout=10)
    assert respuesta.status_code == 200
    id_tarea = respuesta.json().get("id_tarea")
    assert id_tarea is not None

    data = {}
    for _ in range(15):
        consulta = requests.get(f"http://localhost:8080/consulta_tarea/{id_tarea}", timeout=5)
        data = consulta.json()
        if data.get("estado") != "pendiente":
            break
        time.sleep(1)

    assert data.get("estado") != "exito"


def test_request_body_invalido(servidor):
    respuesta = requests.post(SERVIDOR_URL, data="no es json", timeout=10,
                              headers={"Content-Type": "application/json"})
    assert respuesta.status_code == 400
