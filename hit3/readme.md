=====================================================
  HIT #3 — Coordinacion y Tolerancia a Fallos
  Algoritmo Bully + Load Balancer (nginx)
=====================================================

ARQUITECTURA
------------
  Cliente
     |
  nginx:80  (load balancer)
     |
  +--+--+--+
  |        |        |
node1    node2    node3   <- Nodos Bully (coordinacion)
                           El de mayor ID activo = lider
                           El lider envia tareas a workers

  +--------+--------+
  |                 |
worker1           worker2  <- Servidores Hit#1 (ejecutan Docker)


=====================================================
PASO 1 — Crear red Docker
=====================================================

  docker network create hit3-net


=====================================================
PASO 2 — Construir y levantar workers (servidores Hit#1)
=====================================================

  NOTA: Se usa imagen local (servidor-local) en lugar de
  marianocavallo/servidor:latest para evitar conflicto de
  puertos con los nodos (puerto 5001) y para corregir la
  deteccion de IP del host en Docker Desktop.

  (Ejecutar desde la raiz del proyecto tp-sd-concurrencia/)

  docker build -t servidor-local ./hit1/servidor

  docker run -d --name worker1 --network hit3-net -v /var/run/docker.sock:/var/run/docker.sock servidor-local

  docker run -d --name worker2 --network hit3-net -v /var/run/docker.sock:/var/run/docker.sock servidor-local


=====================================================
PASO 3 — Construir imagen del nodo Bully
=====================================================

  (Ejecutar desde la carpeta hit3/)

  docker build -t bully-node ./node


=====================================================
PASO 4 — Levantar los 3 nodos coordinadores
=====================================================

  docker run -d --name node1 --network hit3-net -p 5001:5000 -e NODE_ID=1 -e ALL_NODES="1:node1:5000,2:node2:5000,3:node3:5000" -e WORKERS="worker1:8080,worker2:8080" -e START_DELAY=5 bully-node

  docker run -d --name node2 --network hit3-net -p 5002:5000 -e NODE_ID=2 -e ALL_NODES="1:node1:5000,2:node2:5000,3:node3:5000" -e WORKERS="worker1:8080,worker2:8080" -e START_DELAY=5 bully-node

  docker run -d --name node3 --network hit3-net -p 5003:5000 -e NODE_ID=3 -e ALL_NODES="1:node1:5000,2:node2:5000,3:node3:5000" -e WORKERS="worker1:8080,worker2:8080" -e START_DELAY=5 bully-node

  NOTA: node3 tiene el mayor NODE_ID => gana la primera eleccion.


=====================================================
PASO 5 — Levantar nginx (load balancer)
=====================================================

  (Ejecutar desde la carpeta hit3/)

  docker run -d --name hit3-nginx --network hit3-net -p 80:80 \
    -v "$(pwd)/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
    nginx:alpine

    docker run -d --name hit3-nginx --network hit3-net -p 80:80 -v "$(pwd)/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" nginx:alpine


=====================================================
PASO 6 — Verificar estado del cluster (~6s despues)
=====================================================

  curl.exe http://localhost:5001/estado
  curl.exe http://localhost:5002/estado
  curl.exe http://localhost:5003/estado

  Resultado esperado:
    node3 -> "is_leader": true
    node1 -> "is_leader": false
    node2 -> "is_leader": false


=====================================================
PASO 7 — Probar envio de tarea
=====================================================

  En Linux/Mac:
  curl -X POST http://localhost/ejecutarTareaRemota \
    -H "Content-Type: application/json" \
    -d '{"imagen":"marianocavallo/servicio-tarea:latest","parametros":{"tarea":"suma","a":10,"b":5},"timeout":15}'

  En Windows (PowerShell / terminal de VS Code):
  Invoke-RestMethod -Method POST http://localhost/ejecutarTareaRemota -ContentType "application/json" -Body '{"imagen":"marianocavallo/servicio-tarea:latest","parametros":{"tarea":"suma","a":10,"b":5},"timeout":15}'

  NOTA: Usar Invoke-RestMethod en lugar de curl.exe para evitar problemas
  de quoting con JSON en PowerShell.

  La peticion entra por nginx -> llega a cualquier nodo ->
  si no es lider, reenvía al lider -> el lider asigna al worker.


=====================================================
PASO 8 — Simular caida del coordinador
=====================================================

  docker stop node3

  Esperar 6-8 segundos y verificar:

  curl http://localhost:5001/estado
  curl http://localhost:5002/estado

  Resultado esperado: node2 -> "is_leader": true

  Enviar nueva tarea (sigue funcionando):

  En Linux/Mac:
  curl -X POST http://localhost/ejecutarTareaRemota \
    -H "Content-Type: application/json" \
    -d '{"imagen":"marianocavallo/servicio-tarea:latest","parametros":{"tarea":"suma","a":10,"b":5},"timeout":15}'

  En Windows (PowerShell):
  $body = '{"imagen":"marianocavallo/servicio-tarea:latest","parametros":{"tarea":"suma","a":10,"b":5},"timeout":15}'
  curl.exe -X POST http://localhost/ejecutarTareaRemota -H "Content-Type: application/json" -d $body


=====================================================
LIMPIAR TODO
=====================================================

  docker stop node1 node2 node3 worker1 worker2 hit3-nginx
  docker rm   node1 node2 node3 worker1 worker2 hit3-nginx
  docker network rm hit3-net
  docker rmi servidor-local


=====================================================
COMO FUNCIONA EL ALGORITMO BULLY
=====================================================

  1. Al arrancar: cada nodo espera START_DELAY segundos y envia
     mensajes ELECTION a todos los nodos con ID mayor.

  2. Si nadie responde (OK): el nodo se proclama lider y envia
     COORDINATOR a todos los demas.

  3. Si alguien responde OK: ese nodo inicia su propia eleccion.
     Gana siempre el nodo con mayor ID activo.

  4. Heartbeat: el lider envia un pulso cada 2s a todos.
     Si un nodo no recibe heartbeat en 6s => inicia nueva eleccion.

  5. Redistribucion de tareas: el nuevo lider acepta tareas
     inmediatamente. Durante la transicion (~6-8s) el cliente
     puede recibir 503 y reintentar.

  Tiempo de recuperacion estimado: 6 a 10 segundos.


=====================================================
ENDPOINTS DISPONIBLES
=====================================================

  GET  http://localhost/estado               -> estado via nginx
  GET  http://localhost:500X/estado          -> estado directo nodo X
  POST http://localhost/ejecutarTareaRemota  -> enviar tarea

=====================================================
