import requests

SERVIDOR_URL = "http://localhost:8080/ejecutarTareaRemota"
IMAGEN = "marianocavallo/servicio-tarea:latest"


while True:
    tarea = input("¿Qué tarea querés realizar? (suma/resta): ").strip().lower()
    if tarea in ["suma", "resta"]:
        break
    print("Tarea no válida. Ingresá 'suma' o 'resta'.")

# Pedir números
while True:
    try:
        a = float(input("Ingresá el valor de a: "))
        b = float(input("Ingresá el valor de b: "))
        break
    except ValueError:
        print("Valor no válido. Ingresá un número.")


# Armar payload
payload = {
    "imagen": IMAGEN,
    "parametros": {
        "tarea": tarea,
        "a": a,
        "b": b,
    },
}

# print(f"\nEnviando al servidor: {payload}")

# Enviar al servidor
try:
    response = requests.post(SERVIDOR_URL, json=payload)
    print(f"\nStatus: {response.status_code}")
    print(f"Resultado: {response.json()}")
except requests.exceptions.ConnectionError:
    print("\nError: No se pudo conectar con el servidor. ¿Está corriendo?")

