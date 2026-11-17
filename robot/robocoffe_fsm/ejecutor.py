"""Lazo de ejecucion: lee robot y canal, llama a la maquina y ejecuta sus comandos.

Es el mismo para el robot real y el simulado; solo cambian el robot, el canal y el reloj.
Registra cada transicion en un CSV (fuente de la evidencia que pide el curso).
"""
import csv
import time

from .fsm import Lecturas, RECHAZADO, EN_CURSO, TERMINADO


def _campos(linea):
    return dict(tok.split("=", 1) for tok in linea.split()[2:] if "=" in tok)


class Ejecutor:
    def __init__(self, fsm, robot, canal=None, csv_transiciones=None, log=print,
                 reloj=time.monotonic, dormir=time.sleep, fuente_vaso=None):
        self.fsm, self.robot, self.canal = fsm, robot, canal
        self.reloj, self.dormir, self.log = reloj, dormir, log
        self.fuente_vaso = fuente_vaso or (lambda: False)
        self.t0 = reloj()
        self.t_ultima = -1e9
        self.verif = None
        self.nav_forzado = None
        self.t_inicio_tramo = -1e9
        self._csv = None
        if csv_transiciones:
            self._f = open(csv_transiciones, "w", newline="")
            self._csv = csv.writer(self._f)
            self._csv.writerow(["t", "de", "a", "causa", "orden", "x", "y", "th"])

    def ciclo(self, entradas=()):
        t = self.reloj() - self.t0
        lineas = list(entradas) + (self.canal.leer() if self.canal else [])
        lect = self.robot.leer(t)
        if lect is not None:
            self.t_ultima = t
        nav = lect["nav"] if lect else None
        if self.nav_forzado:
            nav = self.nav_forzado
        elif nav == TERMINADO and t - self.t_inicio_tramo < 0.2:
            nav = EN_CURSO                                  # el status aun no refleja el tramo nuevo
        L = Lecturas(t=t, pose=lect["pose"] if lect else None,
                     enlace_ok=(t - self.t_ultima) < self.fsm.cfg.t_enlace,
                     nav=nav, dist_frontal=lect["dist_frontal"] if lect else None,
                     bateria=lect["bateria"] if lect else None,
                     vaso_retirado=bool(self.fuente_vaso()), verificacion=self.verif)
        self.verif = None                                   # se entrega UNA sola vez
        sal = self.fsm.step(L, lineas)
        for cmd in sal.comandos:
            if cmd[0] == "INICIALIZAR":
                self.verif = self.robot.verificar_inicio(t)
            elif cmd[0] == "TRAMO":
                ok = self.robot.iniciar_tramo(cmd[1], t)
                self.nav_forzado = RECHAZADO if ok is False else None
                self.t_inicio_tramo = t
            elif cmd[0] == "STOP":
                self.robot.detener(t)
                self.nav_forzado = None
            elif cmd[0] == "INDICAR":
                self.robot.indicar(cmd[1], t)
        for linea in sal.respuestas + sal.eventos:
            if self.canal:
                self.canal.enviar(linea)
            if not linea.startswith("EVT LATIDO"):
                self.log(linea)
            if self._csv and linea.startswith("EVT TRANSICION"):
                c = _campos(linea)
                self._csv.writerow([c.get(k) for k in ("t", "de", "a", "causa", "orden", "x", "y", "th")])
                self._f.flush()
        return sal

    def correr(self, duracion=None, hasta=None):
        """Lazo de periodo fijo. hasta: funcion(fsm) -> True para salir."""
        p = self.fsm.cfg.periodo
        inicio = self.reloj()
        while True:
            t_ciclo = self.reloj()
            self.ciclo()
            if hasta and hasta(self.fsm):
                return
            if duracion is not None and self.reloj() - inicio >= duracion:
                return
            resto = p - (self.reloj() - t_ciclo)
            if resto > 0:
                self.dormir(resto)


class RelojSimulado:
    """Reloj para pruebas: avanza solo cuando dormir() se llama (corre mas rapido que real)."""
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def dormir(self, dt):
        self.t += dt
