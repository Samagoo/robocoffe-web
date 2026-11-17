"""Maquina de estados de entrega con el OAK9 real. La maquina corre en esta computadora:
recibe la orden por WiFi (TCP, puerto 9000) y manda cada tramo al robot con oak9lib (puerto 8080).

Uso:
    python main_real.py --host <ip del robot> --entrega 180       # ordenes por TCP en el puerto 9000
    python main_real.py --host <ip del robot> --canal consola     # teclear ordenes (pruebas)
Prueba rapida sin plataforma, desde otra terminal:  nc <ip de esta computadora> 9000  ->  PING id=1

Antes: robot en la guia de la base, mirando al frente (x), bateria cargada, rutas despejadas.
Ordenes (una por linea):  ORDEN id=1 destino=MESA1   |  RETIRADO id=2 |  PAUSA id=3  |  REANUDAR id=4
                          CANCELAR id=5 orden=1      |  RESET id=6    |  ESTADO id=7 |  PING id=8
Contrato completo: docs/02_protocolo.md
Ctrl+C detiene el robot y sale.
"""
import argparse
import time

from robocoffe_fsm.canales import CanalConsola, CanalSerie, CanalTCP
from robocoffe_fsm.config import Config
from robocoffe_fsm.ejecutor import Ejecutor
from robocoffe_fsm.fsm import MaquinaEntrega
from robocoffe_fsm.robot_oak9 import RobotOAK9


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--canal", choices=["tcp", "consola", "serie"], default="tcp")
    ap.add_argument("--puerto", default=None, help="puerto TCP (9000 por defecto) o COMx si --canal serie")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--entrega", type=float, default=None,
                    help="segundos maximos de espera en la mesa (pruebas con registro: 180)")
    a = ap.parse_args()

    cfg = Config()
    if a.entrega is not None:
        cfg.t_entrega = a.entrega
    if a.canal == "serie":
        canal = CanalSerie(a.puerto, a.baud)
    elif a.canal == "tcp":
        canal = CanalTCP(int(a.puerto or 9000))
    else:
        canal = CanalConsola()
    robot = RobotOAK9(a.host, cfg)
    nombre = time.strftime("transiciones_%Y%m%d_%H%M%S.csv")
    ej = Ejecutor(MaquinaEntrega(cfg), robot, canal, csv_transiciones=nombre)
    extra = f" puerto={a.puerto or 9000}" if a.canal == "tcp" else ""
    print(f"[RoboCoffe] ordenes por {a.canal}{extra}  robot={a.host}:8080  registro={nombre}  (Ctrl+C para salir)")
    try:
        ej.correr()
    except KeyboardInterrupt:
        pass
    finally:
        robot.detener(0.0)
        print("[RoboCoffe] robot detenido")


if __name__ == "__main__":
    main()
