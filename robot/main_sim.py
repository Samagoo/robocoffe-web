"""Demostracion sin robot: las tres mesas con un robot simulado, mas un obstaculo y una cancelacion.

    python main_sim.py            -> imprime cada transicion (la evidencia que pide el curso)
                                     y escribe transiciones_sim.csv
"""
from robocoffe_fsm.canales import CanalMemoria
from robocoffe_fsm.config import Config
from robocoffe_fsm.ejecutor import Ejecutor, RelojSimulado
from robocoffe_fsm.fsm import ESPERANDO_ORDEN, MaquinaEntrega
from robocoffe_fsm.robot_sim import RobotSimulado


def esperar(ej, reloj, cond, limite=400):
    t_lim = reloj.t + limite
    while not cond(ej.fsm) and reloj.t < t_lim:
        ej.ciclo()
        reloj.dormir(ej.fsm.cfg.periodo)


def main():
    cfg = Config()
    reloj = RelojSimulado()
    robot = RobotSimulado(obstaculos=[(35.0, 39.0, 0.15)])     # obstaculo durante la Mesa 2
    canal = CanalMemoria()
    ej = Ejecutor(MaquinaEntrega(cfg), robot, canal, csv_transiciones="transiciones_sim.csv",
                  reloj=reloj, dormir=reloj.dormir,
                  log=lambda l: print(f"[{reloj.t:7.2f} s] {l}"))
    libre = lambda f: f.estado == ESPERANDO_ORDEN
    esperar(ej, reloj, libre)
    for i, mesa in enumerate(["MESA1", "MESA2", "MESA3"], start=1):
        canal.entrada.append(f"ORDEN id={i} destino={mesa}")
        ej.ciclo(); reloj.dormir(cfg.periodo)
        esperar(ej, reloj, libre)
    # cancelacion a medio camino de la Mesa 3
    canal.entrada.append("ORDEN id=10 destino=MESA3")
    esperar(ej, reloj, lambda f: f.estado == "RECORRIDO_MESA_3" and f.pose[0] > 1.5)
    canal.entrada.append("CANCELAR id=11 orden=10")
    esperar(ej, reloj, libre)
    print(f"\nPose final del robot simulado: x={robot.x:.3f} m  y={robot.y:.3f} m  th={robot.th:.1f} deg")


if __name__ == "__main__":
    main()
