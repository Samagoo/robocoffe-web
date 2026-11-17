"""Maquina de estados de entrega del OAK9 (RoboCoffe) -- logica pura, sin E/S.

Cada llamada a step() recibe las lecturas del ciclo y los mensajes recibidos, y
regresa los comandos para el robot, las respuestas y los eventos. Asi la misma
maquina corre con el OAK9 real (ordenes por TCP/WiFi, robot por oak9lib) y en
pruebas con un robot simulado.

Reglas del curso (Maquinas de estado, lamina 22): una sola variable de estado,
cambiar() es el unico lugar donde cambia, nada bloquea, se mide desde la entrada
al estado, cada transicion se registra y las fallas son estados.
Cada rama marcada Tn corresponde al renglon n de la tabla de transiciones.
"""
import math
from collections import deque
from dataclasses import dataclass, field

from . import protocolo as P
from .config import Config
from .rutas import RUTAS, ruta_regreso

# ------------------------------------------------------------------ estados
INICIALIZANDO = "INICIALIZANDO"
ESPERANDO_ORDEN = "ESPERANDO_ORDEN"
RECORRIDO_MESA_1 = "RECORRIDO_MESA_1"
RECORRIDO_MESA_2 = "RECORRIDO_MESA_2"
RECORRIDO_MESA_3 = "RECORRIDO_MESA_3"
EN_MESA = "EN_MESA"
REGRESO_BASE = "REGRESO_BASE"
DETENIDO = "DETENIDO"
ERROR = "ERROR"

RECORRIDOS = {RECORRIDO_MESA_1: 1, RECORRIDO_MESA_2: 2, RECORRIDO_MESA_3: 3}
ESTADO_DE_DESTINO = {1: RECORRIDO_MESA_1, 2: RECORRIDO_MESA_2, 3: RECORRIDO_MESA_3}
EN_RUTA = set(RECORRIDOS) | {REGRESO_BASE}

# estado del tramo que reporta el navegador
EN_CURSO, TERMINADO, RECHAZADO = "EN_CURSO", "TERMINADO", "RECHAZADO"


@dataclass
class Lecturas:
    t: float
    pose: tuple = None              # (x [m], y [m], th [deg]) o None si no hubo respuesta
    enlace_ok: bool = True          # respuesta del robot en los ultimos t_enlace s
    nav: str = None                 # EN_CURSO / TERMINADO / RECHAZADO / None
    dist_frontal: float = None      # [m] menor distancia de los ultrasonicos frontales
    bateria: float = None           # [V]
    vaso_retirado: bool = False     # aviso del adaptador (masa < 50 g)
    verificacion: tuple = None      # (ok, detalle) cuando termina la inicializacion


@dataclass
class Salidas:
    comandos: list = field(default_factory=list)    # ("INICIALIZAR",) ("TRAMO", Tramo) ("STOP",) ("INDICAR", texto)
    respuestas: list = field(default_factory=list)  # lineas para el canal de ordenes
    eventos: list = field(default_factory=list)     # lineas EVT (telemetria + registro)


def _ang(a):
    """Angulo a [-180, 180)."""
    return (a + 180.0) % 360.0 - 180.0


class MaquinaEntrega:
    def __init__(self, cfg=None, rutas=None):
        self.cfg = cfg or Config()
        self.rutas = rutas or RUTAS
        # memoria de la maquina
        self.estado = None
        self.t_entrada = 0.0
        self.estado_previo = None
        self.mesa = None
        self.orden_id = None
        self.ruta = []
        self.k = 0
        self.reintentos = 0
        self.atascos = {}
        self.causa = None             # causa de DETENIDO
        self.pausado = False
        self.codigo_error = None
        self.t_tramo = 0.0            # inicio del tramo actual (para T_MAX_TRAMO)
        self.t_max_tramo = 0.0
        self.t_fin_tramo = None       # el navegador termino; asentando hasta t_fin + t_asentar
        self.ref_avance = None        # (t, x, y, th) para detectar atascos
        self.t_despejado = None
        self.pose = None
        self.t_pose = None
        self.dt_pose_prev = self.cfg.periodo
        self.respondidos = {}         # id -> linea de respuesta (idempotencia)
        self.max_id = -1
        self.pendientes = deque()     # mensajes que cambian estado, uno por ciclo
        self.t_latido = -1e9
        self.historial = []           # (t, origen, destino, causa)
        self._sal = None
        self._t = 0.0
        self._primer_paso = True

    # ============================================================ cambiar()
    def cambiar(self, nuevo, causa=""):
        """UNICO lugar donde cambia el estado: registra, publica y ejecuta la entrada."""
        t = self._t
        x, y, th = self.pose if self.pose else (float("nan"),) * 3
        self.historial.append((t, self.estado, nuevo, causa))
        self._sal.eventos.append(P.evento(
            "TRANSICION", t=f"{t:.2f}", de=self.estado, a=nuevo, causa=causa or "-",
            orden=self.orden_id if self.orden_id is not None else "-",
            x=f"{x:.3f}", y=f"{y:.3f}", th=f"{th:.1f}"))
        if self.estado in EN_RUTA and nuevo not in EN_RUTA:
            self._sal.comandos.append(("STOP",))
        self.estado = nuevo
        self.t_entrada = t
        self._entrar(nuevo)

    def _entrar(self, e):
        """Acciones de entrada (columna 'Al entrar' de la seccion 3)."""
        s = self._sal
        if e == INICIALIZANDO:
            s.comandos += [("STOP",), ("INICIALIZAR",)]
            self.codigo_error = None
        elif e == ESPERANDO_ORDEN:
            s.comandos.append(("STOP",))
            s.comandos.append(("INDICAR", "LISTO"))
            self.mesa = self.orden_id = None
            self.ruta, self.k = [], 0
        elif e in RECORRIDOS or e == REGRESO_BASE:
            self._mandar_tramo()
        elif e == EN_MESA:
            s.comandos.append(("STOP",))
            s.comandos.append(("INDICAR", f"MESA {self.mesa}"))
            s.eventos.append(P.evento("LLEGO", t=f"{self._t:.2f}", mesa=self.mesa, orden=self.orden_id))
        elif e == DETENIDO:
            s.comandos.append(("STOP",))
            s.comandos.append(("INDICAR", f"DETENIDO {self.causa}"))
            self.t_despejado = None
        elif e == ERROR:
            s.comandos.append(("STOP",))
            s.comandos.append(("INDICAR", f"ERROR {self.codigo_error}"))
            s.eventos.append(P.evento("ERROR", t=f"{self._t:.2f}", codigo=self.codigo_error,
                                      orden=self.orden_id if self.orden_id is not None else "-",
                                      tramo=f"{self.k + 1}/{len(self.ruta)}" if self.ruta else "-"))

    # ============================================================ tramos
    def _mandar_tramo(self):
        tr = self.ruta[self.k]
        self._sal.comandos.append(("TRAMO", tr))
        self.t_tramo = self._t
        self.t_fin_tramo = None
        self.ref_avance = (self._t,) + tuple(self.pose) if self.pose else None
        c = self.cfg
        if tr.tipo == "IR" and self.pose:
            d = math.hypot(tr.x - self.pose[0], tr.y - self.pose[1])
            dth = abs(_ang(math.degrees(math.atan2(tr.y - self.pose[1], tr.x - self.pose[0])) - self.pose[2])) if d > 1e-3 else 0.0
        else:
            d = 0.0
            dth = abs(_ang(tr.th - self.pose[2])) if self.pose else 180.0
        self.t_max_tramo = d / c.v_avance + c.v_avance / c.a_avance + dth / c.w_giro + c.w_giro / c.a_giro + c.margen_tramo

    def _error_tramo(self):
        """(dentro_de_tolerancia, ex, ey, eth) del tramo actual con la pose asentada."""
        tr = self.ruta[self.k]
        x, y, th = self.pose
        if tr.tipo == "IR":
            ex, ey = tr.x - x, tr.y - y
            return math.hypot(ex, ey) <= self.cfg.tol_pos, ex, ey, 0.0
        eth = _ang(tr.th - th)
        return abs(eth) <= self.cfg.tol_th, 0.0, 0.0, eth

    def _cargar_ruta(self, ruta):
        self.ruta, self.k, self.reintentos, self.atascos = list(ruta), 0, 0, {}

    # ============================================================ paso
    def step(self, lec, mensajes=()):
        self._sal = Salidas()
        self._t = lec.t
        self._actualizar_pose(lec)
        if self._primer_paso:                       # estado inicial
            self._primer_paso = False
            self.estado = None
            self.cambiar(INICIALIZANDO, "arranque")
        self._recibir(mensajes)
        self._transicion(lec)
        if lec.t - self.t_latido >= self.cfg.t_latido:
            self.t_latido = lec.t
            self._sal.eventos.append(P.evento("LATIDO", t=f"{lec.t:.2f}", estado=self.estado,
                                              bat=lec.bateria if lec.bateria is not None else "-"))
        return self._sal

    def _actualizar_pose(self, lec):
        self._salto = None
        if lec.pose is None:
            return
        if self.pose is not None and self.t_pose is not None:
            dt = lec.t - self.t_pose
            salto = math.hypot(lec.pose[0] - self.pose[0], lec.pose[1] - self.pose[1])
            limite = 1.5 * self.cfg.v_avance * (dt + self.dt_pose_prev) + self.cfg.salto_margen
            if salto > limite:
                self._salto = salto
            self.dt_pose_prev = dt
        self.pose, self.t_pose = tuple(lec.pose), lec.t

    # ============================================================ mensajes
    def _recibir(self, lineas):
        for linea in lineas:
            try:
                m = P.parsear(linea)
            except P.ErrorFormato as ex:
                self._sal.respuestas.append(f"ERROR ? id=- FORMATO {str(ex).replace(' ', '_')}")
                continue
            if m.cmd in P.CONSULTAS:
                self._sal.respuestas.append(self._consulta(m))
                continue
            if m.id in self.respondidos:                    # reintento de la plataforma
                self._sal.respuestas.append(self.respondidos[m.id])
                continue
            if m.id <= self.max_id:
                self._responder(m, P.error(m.cmd, m.id, "ID_REPETIDO"))
                continue
            self.max_id = m.id
            self.pendientes.append(m)

    def _consulta(self, m):
        if m.cmd == "PING":
            return P.ok("PING", m.id, estado=self.estado)
        x, y, th = self.pose if self.pose else (float("nan"),) * 3
        return P.ok("ESTADO", m.id, estado=self.estado,
                    orden=self.orden_id if self.orden_id is not None else "-",
                    tramo=f"{self.k + 1}/{len(self.ruta)}" if self.ruta else "-",
                    x=f"{x:.3f}", y=f"{y:.3f}", th=f"{th:.1f}",
                    error=self.codigo_error or "-")

    def _responder(self, m, linea):
        self.respondidos[m.id] = linea
        self._sal.respuestas.append(linea)

    # ============================================================ transiciones
    def _transicion(self, lec):
        """Evalua UNA transicion por ciclo: ERROR > DETENIDO > ordenes > avance."""
        e, c, t_est = self.estado, self.cfg, lec.t - self.t_entrada

        if e == INICIALIZANDO:
            self._rechazar_ordenes(permitidas=())
            if lec.verificacion is not None:
                ok, detalle = lec.verificacion
                if ok:
                    return self.cambiar(ESPERANDO_ORDEN, "verificaciones_ok")             # T1
                self.codigo_error = "E_INIT"
                return self.cambiar(ERROR, f"E_INIT:{detalle}")                           # T2
            if t_est >= c.t_init:
                self.codigo_error = "E_INIT"
                return self.cambiar(ERROR, "E_INIT:timeout")                              # T2
            return

        if e == ESPERANDO_ORDEN:
            m = self._siguiente(permitidas=("ORDEN",))
            if m is None:
                return
            motivo = self._guardas_despacho(m, lec)
            if motivo:
                return self._responder(m, P.error("ORDEN", m.id, motivo))                 # T6
            self.mesa = P.DESTINOS[m.campos["destino"]]
            self.orden_id = m.id
            self._cargar_ruta(self.rutas[self.mesa])
            nuevo = ESTADO_DE_DESTINO[self.mesa]
            self._responder(m, P.ok("ORDEN", m.id, estado=nuevo))
            return self.cambiar(nuevo, f"orden_{m.campos['destino']}")                   # T3-T5

        if e in EN_RUTA:
            return self._en_ruta(lec)

        if e == EN_MESA:
            m = self._siguiente(permitidas=("RETIRADO",))      # aviso de vaso retirado por TCP
            retirado = lec.vaso_retirado or m is not None
            if m is not None:
                self._responder(m, P.ok("RETIRADO", m.id, estado=REGRESO_BASE))
            if retirado or t_est >= c.t_entrega:
                self._cargar_ruta(ruta_regreso(self.ruta, self.k, self.cfg.regreso_en_reversa))
                return self.cambiar(REGRESO_BASE, "vaso_retirado" if retirado else "t_entrega")  # T10
            return

        if e == DETENIDO:
            return self._detenido(lec, t_est)

        if e == ERROR:
            m = self._siguiente(permitidas=("RESET",))
            if m is not None:
                self._responder(m, P.ok("RESET", m.id, estado=INICIALIZANDO))
                self.orden_id, self.ruta = None, []
                return self.cambiar(INICIALIZANDO, "reset")                               # T17

    def _guardas_despacho(self, m, lec):
        c = self.cfg
        if m.campos["destino"] not in P.DESTINOS:
            return "DESTINO_INVALIDO"
        if not lec.enlace_ok or self.pose is None:
            return "SIN_ENLACE_ROBOT"
        if c.bat_min is not None and (lec.bateria is None or lec.bateria < c.bat_min):
            return "BATERIA_BAJA"
        x, y, th = self.pose
        if math.hypot(x, y) > c.base_tol_pos or abs(_ang(th)) > c.base_tol_th:
            return "FUERA_DE_BASE"
        return None

    def _siguiente(self, permitidas):
        """Saca la primera orden pendiente; las no permitidas en este estado se rechazan."""
        while self.pendientes:
            m = self.pendientes.popleft()
            if m.cmd in permitidas:
                return m
            if self.estado == ERROR:
                motivo = "EN_ERROR"
            else:
                motivo = "OCUPADO" if m.cmd == "ORDEN" else "NO_PERMITIDO"
            self._responder(m, P.error(m.cmd, m.id, motivo))
        return None

    def _rechazar_ordenes(self, permitidas):
        self._siguiente(permitidas)

    def _a_error(self, codigo):
        self.codigo_error = codigo
        return self.cambiar(ERROR, codigo)                                                 # T14 / T16

    def _a_detenido(self, causa):
        self.causa, self.estado_previo = causa, self.estado
        return self.cambiar(DETENIDO, causa)                                               # T13

    def _obstaculo(self, lec):
        tr = self.ruta[self.k] if self.ruta else None
        return (tr is not None and tr.tipo == "IR" and self.t_fin_tramo is None
                and lec.dist_frontal is not None and lec.dist_frontal < self.cfg.d_obst)

    def _en_ruta(self, lec):
        c, t = self.cfg, lec.t
        # 1) ERROR (T14)
        if lec.nav == RECHAZADO:
            return self._a_error("E_TRAMO_RECHAZADO")
        if self._salto is not None:
            return self._a_error("E_SALTO_POSE")
        if c.bat_crit is not None and lec.bateria is not None and lec.bateria < c.bat_crit:
            return self._a_error("E_BATERIA")
        if self.t_fin_tramo is None and t - self.t_tramo >= self.t_max_tramo:
            return self._a_error("E_TRAMO_TIMEOUT")
        if self.ref_avance is None and self.pose:
            self.ref_avance = (t,) + tuple(self.pose)
        # 2) DETENIDO (T13)
        if not lec.enlace_ok:
            return self._a_detenido("ENLACE")
        if self._obstaculo(lec):
            return self._a_detenido("OBSTACULO")
        if self.t_fin_tramo is None and lec.nav == EN_CURSO and self.pose and self.ref_avance:
            t0, x0, y0, th0 = self.ref_avance
            x, y, th = self.pose
            if math.hypot(x - x0, y - y0) > c.d_atasco or abs(_ang(th - th0)) > c.th_atasco:
                self.ref_avance = (t, x, y, th)
            elif t - t0 >= c.t_atasco:
                self.atascos[self.k] = self.atascos.get(self.k, 0) + 1
                return self._a_detenido("ATASCO")
        # 3) ordenes
        permitidas = ("PAUSA", "CANCELAR") if self.estado in RECORRIDOS else ("PAUSA",)
        m = self._siguiente(permitidas)
        if m is not None:
            if m.cmd == "PAUSA":
                self._responder(m, P.ok("PAUSA", m.id, estado=DETENIDO))
                self.pausado = True
                return self._a_detenido("PAUSA")
            if m.campos.get("orden") != str(self.orden_id):
                return self._responder(m, P.error("CANCELAR", m.id, "ORDEN_NO_COINCIDE"))
            self._responder(m, P.ok("CANCELAR", m.id, estado=REGRESO_BASE))
            self._cargar_ruta(ruta_regreso(self.ruta, self.k, self.cfg.regreso_en_reversa))
            return self.cambiar(REGRESO_BASE, "cancelada")                                 # T12
        # 4) avance normal
        if self.t_fin_tramo is None:
            if lec.nav == TERMINADO:
                self.t_fin_tramo = t
                self._sal.comandos.append(("STOP",))       # limpia la integral del PID de rueda
            return
        if t - self.t_fin_tramo < c.t_asentar or self.pose is None:
            return
        ok, ex, ey, eth = self._error_tramo()
        self._sal.eventos.append(P.evento("TRAMO", t=f"{t:.2f}", orden=self.orden_id if self.orden_id is not None else "-",
                                          tramo=f"{self.k + 1}/{len(self.ruta)}", tipo=self.ruta[self.k].tipo,
                                          ex=f"{ex:.3f}", ey=f"{ey:.3f}", eth=f"{eth:.1f}",
                                          reintentos=self.reintentos, ok=ok))
        if not ok:
            if self.reintentos < c.n_reintentos:
                self.reintentos += 1
                return self._mandar_tramo()                                                # T8
            return self._a_error("E_POSICION")                                             # T14
        if self.k + 1 < len(self.ruta):
            self.k += 1
            self.reintentos = 0
            return self._mandar_tramo()                                                    # T7
        if self.estado in RECORRIDOS:
            return self.cambiar(EN_MESA, "ultimo_tramo")                                   # T9
        return self.cambiar(ESPERANDO_ORDEN, "en_base")                                    # T11

    def _detenido(self, lec, t_est):
        c = self.cfg
        # 1) ERROR (T16)
        if self.causa != "PAUSA" and t_est >= c.t_max_detenido:
            return self._a_error("E_DETENIDO_TIMEOUT")
        if self.causa == "ATASCO" and self.atascos.get(self.k, 0) >= 2:
            return self._a_error("E_ATASCO")
        # 3) ordenes: solo REANUDAR (si la causa fue PAUSA)
        m = self._siguiente(("REANUDAR",))
        if m is not None:
            if self.causa == "PAUSA":
                self._responder(m, P.ok("REANUDAR", m.id, estado=self.estado_previo))
                self.pausado = False
            else:
                self._responder(m, P.error("REANUDAR", m.id, "NO_PERMITIDO"))
        # 4) causa despejada durante T_DESPEJE (T15)
        if self.pausado:
            return
        libre = lec.enlace_ok and lec.pose is not None
        tr = self.ruta[self.k]
        if tr.tipo == "IR" and lec.dist_frontal is not None and lec.dist_frontal < c.d_obst:
            libre = False
        if self.causa == "PAUSA" and not self.pausado:
            self.t_despejado = lec.t - c.t_despeje        # reanudar de inmediato
        if not libre:
            self.t_despejado = None
            return
        if self.t_despejado is None:
            self.t_despejado = lec.t
        if lec.t - self.t_despejado >= c.t_despeje:
            previo = self.estado_previo
            self.causa = None
            self.cambiar(previo, "reanuda")                                                # T15
