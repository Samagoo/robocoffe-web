"""Navegador de lazo cerrado (girar y avanzar con la pose medida) -- el MISMO en Webots y en el OAK9.

Por que existe: en la prueba del 2 nov 2026 go2point del firmware termino cada giro ~38 grados
antes y cada avance ~5 cm antes, y no corrige el rumbo al avanzar. Este navegador cierra el
lazo con la pose (encoders + giroscopio) hasta llegar, como el modo PC de probar_movimiento.py,
pero sin bloquear: la maquina de estados lo llama una vez por ciclo.

Uso:
    nav = NavegadorPC()
    nav.iniciar(tramo, pose, t)                 # tramo.tipo "IR" (x, y) o "GIRAR" (th)
    izq, der, estado = nav.paso(pose, t)        # deg/s de rueda; estado EN_CURSO / TERMINADO
pose = (x [m], y [m], th [grados]) de o1, el centro entre ruedas.
Rueda derecha + e izquierda - = giro antihorario (th crece).
"""
import math

EN_CURSO, TERMINADO = "EN_CURSO", "TERMINADO"


def _ang(a):
    return (a + 180.0) % 360.0 - 180.0


def _lim(v, lo, hi):
    return max(lo, min(hi, v))


class NavegadorPC:
    def __init__(self, rho=0.034, L=0.1663, v_avance=0.10, a_avance=0.10,
                 k_th=2.0, k_d=1.0, k_rumbo=2.0, w_min_recta=30.0, w_min_giro=45.0,
                 w_max=150.0, tol_pos=0.01, tol_th=2.0, dt_lento=0.5, realinear_deg=30.0):
        self.rho, self.L = rho, L
        self.v_avance, self.a_avance = v_avance, a_avance
        self.k_th, self.k_d, self.k_rumbo = k_th, k_d, k_rumbo
        self.w_min_recta, self.w_min_giro, self.w_max = w_min_recta, w_min_giro, w_max
        self.tol_pos, self.tol_th, self.dt_lento = tol_pos, tol_th, dt_lento
        self.realinear = realinear_deg
        self.fase = None              # None, "GIRO", "AVANCE"
        self.tramo = None
        self.t_prev = None
        self.e_prev = None
        self.v_prev = 0.0

    @property
    def activo(self):
        return self.fase is not None

    def _rumbo_obj(self, pose):
        """Rumbo que debe tener el robot: hacia el punto (o de espaldas a el si va en reversa)."""
        tr = self.tramo
        if tr.tipo == "GIRAR":
            return tr.th
        b = math.degrees(math.atan2(tr.y - pose[1], tr.x - pose[0]))
        return b + 180.0 if getattr(tr, "reversa", False) else b

    def iniciar(self, tramo, pose, t):
        self.tramo, self.t_prev, self.e_prev, self.v_prev = tramo, t, None, 0.0
        if tramo.tipo == "IR" and math.hypot(tramo.x - pose[0], tramo.y - pose[1]) <= self.tol_pos:
            self.fase = None          # ya esta ahi
        else:
            self.fase = "GIRO"

    def detener(self):
        self.fase, self.tramo = None, None

    def paso(self, pose, t):
        if self.fase is None:
            return 0.0, 0.0, TERMINADO
        dt = t - self.t_prev
        self.t_prev = t
        if dt > self.dt_lento:                         # dato viejo (WiFi): no mover a ciegas
            self.v_prev = 0.0
            return 0.0, 0.0, EN_CURSO
        k = self.L / (2.0 * self.rho)                  # deg/s de rueda por deg/s de giro del robot
        tr = self.tramo

        if self.fase == "GIRO":
            e = _ang(self._rumbo_obj(pose) - pose[2])
            cruzo = self.e_prev is not None and e * self.e_prev < 0 and abs(e) < 3 * self.tol_th
            self.e_prev = e
            if abs(e) < self.tol_th or cruzo:
                if tr.tipo == "GIRAR":
                    self.fase = None
                    return 0.0, 0.0, TERMINADO
                self.fase, self.e_prev, self.v_prev = "AVANCE", None, 0.0
                return 0.0, 0.0, EN_CURSO
            w = math.copysign(_lim(abs(k * self.k_th * e), self.w_min_giro, self.w_max), e)
            return -w, w, EN_CURSO

        # AVANCE (adelante o en reversa), corrigiendo el rumbo hacia el punto
        dx, dy = tr.x - pose[0], tr.y - pose[1]
        th = math.radians(pose[2])
        signo = -1.0 if getattr(tr, "reversa", False) else 1.0
        ed = signo * (dx * math.cos(th) + dy * math.sin(th))   # lo que falta en la direccion de avance
        if ed < self.tol_pos:                                   # llego (o ya lo paso)
            self.fase = None
            return 0.0, 0.0, TERMINADO
        e_rumbo = _ang(self._rumbo_obj(pose) - pose[2]) if math.hypot(dx, dy) > 0.05 else 0.0
        if abs(e_rumbo) > self.realinear:                       # se desvio mucho: volver a girar
            self.fase, self.e_prev = "GIRO", None
            return 0.0, 0.0, EN_CURSO
        v = min(self.k_d * ed, self.v_avance, self.v_prev + self.a_avance * dt)
        self.v_prev = v
        base = max(math.degrees(v / self.rho), self.w_min_recta)
        corr = _lim(k * self.k_rumbo * e_rumbo, -0.5 * base, 0.5 * base)
        if signo > 0:
            return base - corr, base + corr, EN_CURSO
        return -base - corr, -base + corr, EN_CURSO
