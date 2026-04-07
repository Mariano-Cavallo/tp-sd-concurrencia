from flask import Flask, request, jsonify
import threading
import time
import requests
import os

app = Flask(__name__)

NODE_ID = int(os.environ["NODE_ID"])
PORT = int(os.environ.get("PORT", 5000))

# ALL_NODES format: "1:node1:5000,2:node2:5000,3:node3:5000"
ALL_NODES = {}
for entry in os.environ.get("ALL_NODES", "").split(","):
    if entry.strip():
        nid, host, port = entry.strip().split(":")
        ALL_NODES[int(nid)] = f"http://{host}:{port}"

WORKERS = [w.strip() for w in os.environ.get("WORKERS", "").split(",") if w.strip()]

lock = threading.Lock()
leader_id = None
in_election = False
last_hb = time.time()
worker_idx = 0


# Inicia el algoritmo de elección Bully: envía mensajes de elección a todos los nodos
# con ID mayor. Si ninguno responde, este nodo se proclama líder.
def start_election():
    global in_election, leader_id
    with lock:
        if in_election:
            return
        in_election = True

    print(f"[Node {NODE_ID}] Starting election...", flush=True)
    higher = {nid: url for nid, url in ALL_NODES.items() if nid > NODE_ID}
    got_ok = False

    for nid, url in higher.items():
        try:
            r = requests.post(f"{url}/bully/election", json={"from": NODE_ID}, timeout=2)
            if r.status_code == 200:
                got_ok = True
        except Exception:
            pass

    with lock:
        in_election = False

    if not got_ok:
        become_leader()


# Establece este nodo como líder y notifica a todos los demás nodos mediante
# el mensaje de coordinador del protocolo Bully.
def become_leader():
    global leader_id
    with lock:
        leader_id = NODE_ID
    print(f"[Node {NODE_ID}] I am the new coordinator!", flush=True)
    for nid, url in ALL_NODES.items():
        if nid != NODE_ID:
            try:
                requests.post(f"{url}/bully/coordinator",
                              json={"leader_id": NODE_ID}, timeout=2)
            except Exception:
                pass


# Loop continuo que corre en un hilo separado. Si el nodo es líder, envía heartbeats
# a todos los demás cada 2 segundos. Si es seguidor y no recibe heartbeat en 6 segundos,
# asume que el líder cayó e inicia una nueva elección.
def heartbeat_loop():
    global leader_id, last_hb
    while True:
        time.sleep(2)
        with lock:
            am_leader = (leader_id == NODE_ID)
            cur_leader = leader_id

        if am_leader:
            for nid, url in ALL_NODES.items():
                if nid != NODE_ID:
                    try:
                        requests.post(f"{url}/bully/heartbeat",
                                      json={"leader_id": NODE_ID}, timeout=1)
                    except Exception:
                        pass
        else:
            elapsed = time.time() - last_hb
            if cur_leader is not None and elapsed > 6:
                print(f"[Node {NODE_ID}] Leader {cur_leader} down ({elapsed:.1f}s sin HB), elección!", flush=True)
                with lock:
                    leader_id = None
                start_election()


# Endpoint que recibe un mensaje de elección de otro nodo. Si este nodo tiene ID mayor,
# responde OK e inicia su propia elección en un hilo separado.
@app.route("/bully/election", methods=["POST"])
def bully_election():
    sender = request.get_json()["from"]
    if NODE_ID > sender:
        threading.Thread(target=start_election, daemon=True).start()
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 404


# Endpoint que recibe el mensaje de coordinador. Actualiza el líder conocido,
# cancela cualquier elección en curso y resetea el timestamp del último heartbeat.
@app.route("/bully/coordinator", methods=["POST"])
def bully_coordinator():
    global leader_id, last_hb, in_election
    data = request.get_json()
    with lock:
        leader_id = data["leader_id"]
        in_election = False
    last_hb = time.time()
    print(f"[Node {NODE_ID}] Nuevo líder: {leader_id}", flush=True)
    return jsonify({"ok": True})


# Endpoint que recibe el heartbeat del líder. Actualiza el timestamp para que
# heartbeat_loop sepa que el líder sigue activo.
@app.route("/bully/heartbeat", methods=["POST"])
def bully_heartbeat():
    global last_hb
    last_hb = time.time()
    return jsonify({"ok": True})


# Endpoint de consulta que devuelve el estado actual del nodo: su ID, el líder actual,
# si él mismo es el líder, y la lista de workers configurados.
@app.route("/estado")
def estado():
    with lock:
        return jsonify({
            "node_id": NODE_ID,
            "leader_id": leader_id,
            "is_leader": leader_id == NODE_ID,
            "workers": WORKERS,
        })


# Endpoint para ejecutar una tarea remota. Si el nodo no es líder, reenvía la solicitud
# al líder actual. Si es líder, distribuye la tarea a un worker usando round-robin.
@app.route("/ejecutarTareaRemota", methods=["POST"])
def ejecutar():
    global worker_idx
    with lock:
        am_leader = (leader_id == NODE_ID)
        cur_leader = leader_id

    # Si no soy líder, reenvío al líder
    if not am_leader:
        if cur_leader and cur_leader in ALL_NODES:
            try:
                r = requests.post(
                    f"{ALL_NODES[cur_leader]}/ejecutarTareaRemota",
                    json=request.get_json(), timeout=60
                )
                return jsonify(r.json()), r.status_code
            except Exception as e:
                return jsonify({"error": f"Líder no disponible: {e}"}), 503
        return jsonify({"error": "Sin líder elegido aún"}), 503

    # Soy el líder: asigno a un worker en round-robin
    if not WORKERS:
        return jsonify({"error": "Sin workers configurados"}), 503

    with lock:
        worker = WORKERS[worker_idx % len(WORKERS)]
        worker_idx += 1

    print(f"[Node {NODE_ID}] Asignando tarea a worker: {worker}", flush=True)
    try:
        r = requests.post(
            f"http://{worker}/ejecutarTareaRemota",
            json=request.get_json(), timeout=60
        )
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    delay = int(os.environ.get("START_DELAY", 1))
    print(f"[Node {NODE_ID}] Esperando {delay}s antes de iniciar elección...", flush=True)
    time.sleep(delay)
    threading.Thread(target=start_election, daemon=True).start()
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, threaded=True)
