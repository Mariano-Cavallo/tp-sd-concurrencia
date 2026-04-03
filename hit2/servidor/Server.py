from flask import Flask, request, jsonify
import docker
from docker.errors import ImageNotFound, APIError
import requests
import time
import os
import subprocess
import threading
from queue import Queue
from typing import List

"""
IDEA GENERAL: cuando hay workers disponibles, se le asigna una tarea a cualquiera de ellos. Cuando no hay workers disponibles, el hilo 
main se fija cual es el worker que esta hace mas tiempo ejecutando una tarea (mediante el atributo timestamp) y le agrega a la cola 
de ese worker una tarea pendiente a ejecutar, ademas la agrega a una cola principal



"""

app = Flask(__name__)




class Worker():
    def __init__(self, id_worker,target):
        self.id_worker=id_worker
        self.ocupado=False
        self.tarea_asignada=None
        self.imagen=None
        self.hilo_worker = threading.Thread(target=target, args=(self,))    
        self.aviso_tarea = threading.Condition()
        self.timestamp=None ##minuto exacto en el cual el worker empezo a ejecutar la tarea

        

def ejecutar_tarea(worker):
    while True:
        with worker.



lista_workers: List[Worker] = []
cola = Queue(maxsize=10)

cantidad_workers = 3
for i in range(cantidad_workers):
    trabajador=Worker(i,ejecutar_tarea)
   
    lista_workers.append(trabajador)
    trabajador.hilo_worker.start()

##el codigo de abajo iria adentro de la funcion que recibe el request
worker_disponibles=False
for worker in lista_workers:
    if not worker.ocupado:
        worker_disponibles=True
        ##worker.tarea_asignada=request.get_json()
        with worker.aviso_tarea:
            worker.aviso_tarea.notify_all()
        break    
if not worker_disponibles:
    ##cola.put(request.get_json)
    
##este codigo de arriba lo podria hacer un hilo aparte (con el objetivo de que el servidor pueda seguir recibiendo POSTS)

    