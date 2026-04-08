# Tests - HIT 3

## Prerequisitos

### 1. Imágenes Docker construidas

Desde la raíz del proyecto (`tp-sd-concurrencia/`):

```bash
docker build -t servidor-local ./hit1/servidor
```

Desde la carpeta `hit3/`:

```bash
docker build -t bully-node ./node
```

### 2. Dependencias Python

```bash
pip install pytest requests
```

---

## Cómo correr los tests

Los tests levantan y bajan toda la infraestructura solos (red, workers, nodos, nginx).
Solo hace falta tener las imágenes construidas del paso anterior.

Desde la carpeta `hit3/tests/`:

```bash
pytest test.py -v
```

---

## Qué levanta el fixture automáticamente

| Contenedor   | Imagen          | Rol                          |
|--------------|-----------------|------------------------------|
| `worker1`    | `servidor-local`| Worker hit1 (ejecuta Docker) |
| `worker2`    | `servidor-local`| Worker hit1 (ejecuta Docker) |
| `node1`      | `bully-node`    | Nodo Bully (NODE_ID=1)       |
| `node2`      | `bully-node`    | Nodo Bully (NODE_ID=2)       |
| `node3`      | `bully-node`    | Nodo Bully (NODE_ID=3, líder)|
| `hit3-nginx` | `nginx:alpine`  | Load balancer                |

Red Docker: `hit3-net`

> Al finalizar los tests, todos los contenedores y la red son eliminados automáticamente.

---

## Tests incluidos

| Test | Descripción |
|------|-------------|
| `test_eleccion_inicial_lider_es_node3` | node3 (mayor ID) gana la elección inicial |
| `test_seguidores_conocen_al_lider` | node1 y node2 reportan a node3 como líder |
| `test_estado_incluye_workers` | El endpoint `/estado` lista los workers |
| `test_tarea_suma_via_nginx` | Suma enviada por nginx devuelve resultado correcto |
| `test_tarea_resta_via_nginx` | Resta enviada por nginx devuelve resultado correcto |
| `test_tarea_desde_seguidor_reenvio_al_lider` | Un seguidor reenvía la tarea al líder |
| `test_sin_lider_retorna_503` | Verificación de que siempre hay líder conocido |
| `test_failover_caida_del_lider` | Al caer node3, node2 asume el liderazgo en ~6-10s |
| `test_tarea_tras_failover` | El sistema procesa tareas con el nuevo líder |
| `test_recuperacion_node3_recupera_liderazgo` | node3 al volver inicia nueva elección y recupera el liderazgo (mayor ID gana) |
