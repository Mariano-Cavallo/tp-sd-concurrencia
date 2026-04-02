import subprocess
import time
import requests
import pytest

SERVIDOR_URL = "http://localhost:8080/ejecutarTareaRemota"
IMAGEN = "marianocavallo/servicio-tarea:latest"


@pytest.fixture(scope="module")
def servidor():
    # Levanta el contenedor del servidor
    proc = subprocess.Popen([
        "docker", "run", "--rm",
        "-p", "8080:8080",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "marianocavallo/servidor:latest"
    ])

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

    yield  # corre el test

    proc.terminate()
    proc.wait()


def test_suma_e2e(servidor):
    payload = {
        "imagen": IMAGEN,
        "parametros": {
            "tarea": "suma",
            "a": 10,
            "b": 5
        }
    }
    respuesta = requests.post(SERVIDOR_URL, json=payload, timeout=30)
    assert respuesta.status_code == 200
    assert respuesta.json()["resultado"] == 15


def test_resta_e2e(servidor):
    payload = {
        "imagen": IMAGEN,
        "parametros": {
            "tarea": "resta",
            "a": 10,
            "b": 5
        }
    }
    respuesta = requests.post(SERVIDOR_URL, json=payload, timeout=30)
    assert respuesta.status_code == 200
    assert respuesta.json()["resultado"] == 5