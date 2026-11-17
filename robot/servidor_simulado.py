"""Robot simulado por TCP: para desarrollar la plataforma web SIN el robot y SIN Webots.

Corre la MISMA maquina de estados que main_real.py y habla el MISMO protocolo en el puerto 9000;
solo cambia el robot (cinematico, en memoria). Lo que funcione aqui funciona con el robot real.

    python servidor_simulado.py                       # tiempo real, espera en la mesa 10 s
    python servidor_simulado.py --entrega 180         # como en la operacion real (NFR-01: 180 s)
    python servidor_simulado.py --rapido 5            # todo 5 veces mas rapido (pruebas de UI)

Fallas que puedes provocar escribiendo en ESTA terminal (para probar las pantallas de error):
    obstaculo   algo frente al robot 4 s     -> DETENIDO causa=OBSTACULO, luego reanuda solo
    corte       se cae el WiFi del robot 3 s -> DETENIDO causa=ENLACE, luego reanuda solo
    atasco      las ruedas no avanzan 5 s    -> DETENIDO causa=ATASCO
    salto       la pose salta 0.5 m          -> ERROR E_SALTO_POSE (se sale con RESET)
    estado      imprime estado y pose
Ctrl+C para salir.
"""
import argparse
import sys
import threading
import time

from robocoffe_fsm.canales import CanalTCP
from robocoffe_fsm.config import Config
from robocoffe_fsm.ejecutor import Ejecutor
from robocoffe_fsm.fsm import MaquinaEntrega
from robocoffe_fsm.robot_sim import RobotSimulado


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=9000)
    ap.add_argument("--entrega", type=float, default=None, help="segundos maximos de espera en la mesa")
    ap.add_argument("--rapido", type=float, default=1.0, help="factor de tiempo (1 = tiempo real)")
    ap.add_argument("--reversa", action="store_true", help="regresar a la base de espaldas")
    a = ap.parse_args()

    cfg = Config()
    if a.entrega is not None:
        cfg.t_entrega = a.entrega
    cfg.regreso_en_reversa = a.reversa
    f = max(a.rapido, 0.1)
    t0 = time.monotonic()
    reloj = lambda: (time.monotonic() - t0) * f              # tiempo de la simulacion
    dormir = lambda s: time.sleep(s / f)

    robot = RobotSimulado(v=cfg.v_avance)
    canal = CanalTCP(a.puerto)
    ej = Ejecutor(MaquinaEntrega(cfg), robot, canal, csv_transiciones=None, reloj=reloj, dormir=dormir,
                  log=lambda l: print(f"[{reloj():8.2f} s] {l}", flush=True))

    def fallas():
        for linea in sys.stdin:
            cmd, t = linea.strip().lower(), ej.reloj() - ej.t0
            if cmd == "obstaculo":
                robot.obstaculos.append((t, t + 4.0, 0.15))
            elif cmd == "corte":
                robot.cortes.append((t, t + 3.0))
            elif cmd == "atasco":
                robot.atascos.append((t, t + 5.0))
            elif cmd == "salto":
                robot.salto_en, robot._salto_hecho = t, False
            elif cmd == "estado":
                m = ej.fsm
                print(f"  estado={m.estado} orden={m.orden_id} pose=({robot.x:.2f}, {robot.y:.2f}, {robot.th:.0f}) "
                      f"clientes={len(canal.clientes)}", flush=True)
                continue
            elif cmd:
                print("  fallas: obstaculo | corte | atasco | salto | estado", flush=True)
                continue
            else:
                continue
            print(f"  -> falla '{cmd}' inyectada", flush=True)

    threading.Thread(target=fallas, daemon=True).start()
    print(f"[sim] Robot simulado escuchando en el puerto {a.puerto}  (x{f:g}, espera en mesa {cfg.t_entrega:g} s)")
    print("[sim] Conectate con:  python consola_ordenes.py   o tu backend a 127.0.0.1:9000")
    print("[sim] Fallas: obstaculo | corte | atasco | salto | estado     Ctrl+C para salir", flush=True)
    try:
        ej.correr()
    except KeyboardInterrupt:
        print("\n[sim] fin")


if __name__ == "__main__":
    main()
