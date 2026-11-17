"""Robot simulado (cinematico) con la misma interfaz que RobotOAK9.

Emula go2point (gira hacia el punto y avanza recto) y el giro a un rumbo, y
permite inyectar fallas para probar cada transicion: cortes de enlace,
obstaculos, atascos, tramos que se quedan cortos, rechazo del firmware y saltos
de pose. No modela aceleraciones: sirve para probar la LOGICA, no la dinamica.
"""
import math


def _ang(a):
    return (a + 180.0) % 360.0 - 180.0


class RobotSimulado:
    def __init__(self, v=0.15, w=90.0, pose=(0.0, 0.0, 0.0), corto=0.0,
                 cortes=(), obstaculos=(), atascos=(), rechazar_en=None, salto_en=None,
                 init_ok=True):
        self.v, self.w = v, w
        self.x, self.y, self.th = pose
        self.corto = corto              # fraccion del tramo que se queda corto (0.1 = 10 %)
        self.cortes = list(cortes)      # [(t0, t1)] sin respuesta del robot
        self.obstaculos = list(obstaculos)  # [(t0, t1, dist_m)]
        self.atascos = list(atascos)    # [(t0, t1)] ruedas sin moverse aunque haya tramo
        self.rechazar_en = rechazar_en  # indice del tramo (0, 1, ...) que el firmware rechaza
        self.salto_en = salto_en        # t en que la pose salta 0.5 m
        self.init_ok = init_ok
        self.objetivo = None            # ("IR", x, y) o ("GIRAR", th)
        self.n_tramos = 0
        self.t = 0.0
        self._salto_hecho = False
        self.recorrido = 0.0            # distancia total recorrida (para pruebas)

    # ------------------------------------------------------------ fisica
    def _avanzar(self, t):
        dt, self.t = t - self.t, t
        if self.objetivo is None or dt <= 0:
            return
        if any(a <= t < b for a, b in self.atascos):
            return
        if self.objetivo[0] == "GIRAR":
            e = _ang(self.objetivo[1] - self.th)
            paso = self.w * dt
            if abs(e) <= paso:
                self.th, self.objetivo = self.objetivo[1], None
            else:
                self.th += math.copysign(paso, e)
            return
        _, gx, gy, rev = self.objetivo
        dx, dy = gx - self.x, gy - self.y
        d = math.hypot(dx, dy)
        if d < 1e-4:
            self.objetivo = None
            return
        rumbo = math.degrees(math.atan2(dy, dx)) + (180.0 if rev else 0.0)
        e = _ang(rumbo - self.th)
        if abs(e) > 0.5:                               # fase de giro
            paso = self.w * dt
            self.th = rumbo if abs(e) <= paso else self.th + math.copysign(paso, e)
            return
        paso = self.v * dt
        if paso >= d:
            self.x, self.y, self.objetivo = gx, gy, None
            self.recorrido += d
        else:
            self.x += paso * dx / d
            self.y += paso * dy / d
            self.recorrido += paso

    def _sin_enlace(self, t):
        return any(a <= t < b for a, b in self.cortes)

    # ------------------------------------------------------------ interfaz
    def verificar_inicio(self, t=0.0):
        self.x = self.y = self.th = 0.0
        return (True, "ok") if self.init_ok else (False, "cpr_distinto")

    def leer(self, t):
        self._avanzar(t)
        if self.salto_en is not None and t >= self.salto_en and not self._salto_hecho:
            self._salto_hecho = True
            self.x += 0.5
        if self._sin_enlace(t):
            return None
        dist = 2.0
        for a, b, d in self.obstaculos:
            if a <= t < b:
                dist = d
        return {"pose": (self.x, self.y, self.th),
                "nav": "EN_CURSO" if self.objetivo is not None else "TERMINADO",
                "dist_frontal": dist, "bateria": 7.8}

    def iniciar_tramo(self, tramo, t):
        self._avanzar(t)
        if self._sin_enlace(t):
            return None                                 # no llego el comando
        i = self.n_tramos
        self.n_tramos += 1
        if self.rechazar_en is not None and i == self.rechazar_en:
            return False
        if tramo.tipo == "GIRAR":
            self.objetivo = ("GIRAR", tramo.th)
        else:
            gx, gy = tramo.x, tramo.y
            if self.corto:
                gx = self.x + (gx - self.x) * (1 - self.corto)
                gy = self.y + (gy - self.y) * (1 - self.corto)
            self.objetivo = ("IR", gx, gy, tramo.reversa)
        return True

    def detener(self, t):
        self._avanzar(t)
        self.objetivo = None

    def indicar(self, texto, t=0.0):
        pass
