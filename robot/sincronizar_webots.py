"""Copia el paquete y las herramientas al controlador de Webots (Webots necesita el codigo junto al controlador).

    python sincronizar_webots.py

Correrlo despues de cambiar cualquier archivo de robocoffe_fsm/ o de las herramientas de ordenes.
tests/test_copias_sincronizadas.py falla si se olvida.
"""
import os
import shutil

AQUI = os.path.dirname(os.path.abspath(__file__))
DESTINO = os.path.join(AQUI, "webots", "controllers", "oak9_entregas")
# robot_oak9.py (oak9lib) y robot_sim.py no van: Webots usa su propio adaptador robot_webots.py
PAQUETE = ["__init__.py", "canales.py", "config.py", "ejecutor.py", "fsm.py", "movimiento.py",
           "protocolo.py", "rutas.py"]
HERRAMIENTAS = ["consola_ordenes.py", "enviar_orden.py", "registro_pruebas.py"]


def pares():
    for f in PAQUETE:
        yield os.path.join(AQUI, "robocoffe_fsm", f), os.path.join(DESTINO, "robocoffe_fsm", f)
    for f in HERRAMIENTAS:
        yield os.path.join(AQUI, f), os.path.join(DESTINO, f)


if __name__ == "__main__":
    for origen, destino in pares():
        shutil.copy2(origen, destino)
        print(f"copiado {os.path.relpath(destino, AQUI)}")
