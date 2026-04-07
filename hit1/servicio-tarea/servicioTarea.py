import os
from flask import Flask, jsonify, request

app = Flask(__name__)


def suma(a, b):
    return a + b


def resta(a, b):
    return a - b


@app.route("/ejecutarTarea", methods=["POST"])
def ejecutarTarea():
    data = request.get_json()
    tarea = data.get("tarea")
    a = data.get("a")
    b = data.get("b")

    resultado = None
    if tarea == "suma":
        resultado = suma(a, b)
    elif tarea == "resta":
        resultado = resta(a, b)

    if resultado is not None:
        response = jsonify({"resultado": resultado})

        @response.call_on_close
        def shutdown():
            os._exit(0)  

        return response, 200

    return jsonify({"error": "Tarea no válida"}), 400


if __name__ == "__main__":
    # debug=False es crítico para evitar procesos hijos que impidan el cierre
    app.run(host="0.0.0.0", port=5000, debug=False)
