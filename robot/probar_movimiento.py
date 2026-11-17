"""Prueba de movimiento del OAK9 desde la terminal (sin maquina de estados ni plataforma).

Tu escribes el comando, el robot recorre la ruta y la terminal muestra en vivo la pose y,
al final de cada tramo, el error contra el punto pedido. Todo queda en un CSV.

Uso:   python probar_movimiento.py                  (usa HOST de abajo)
       python probar_movimiento.py 192.168.99.254

Comandos (mayusculas o minusculas, con o sin espacio):
    MESA1  MESA2  MESA3   ir a la mesa desde la base
    BASE                  regresar a la base por los mismos puntos y girar a 0 grados
    IR x y                ir a un punto cualquiera, en metros       (ej.  IR 0.5 0)
    GIRAR th              girar en su lugar al rumbo th, en grados  (ej.  GIRAR 90)
    POSE                  mostrar la pose que cree el robot
    CERO                  pose en (0, 0, 0): SOLO con el robot en la base, mirando al frente
    VEL v                 velocidad de avance en m/s                (ej.  VEL 0.15)
    SALIR
Ctrl+C durante un movimiento = PARO inmediato (vuelves al prompt).

Marco: origen en la base, x al frente, y a la izquierda (derecha = y negativa), theta en grados.

Modo de movimiento (variable MODO):
  PC        (por defecto) gira y avanza con wheel_velocity controlado desde esta computadora,
            con la pose medida hasta llegar; corrige el rumbo al avanzar y pausa las ruedas si
            el WiFi tarda mas de 0.5 s.
  FIRMWARE  go2point del firmware. En la prueba del 2 nov termino cada giro ~38 grados antes
            y cada avance ~5 cm antes; solo para comparar.
"""
import csv
import math
import sys
import time

from oak9 import Robot

# ================================================================== CONFIGURACION
HOST = "192.168.99.254"           # IP de TU robot
V_AVANCE = 0.10                   # [m/s] empieza lento; luego 0.15
A_AVANCE = 0.10                   # [m/s^2]
W_GIRO, A_GIRO = 90.0, 120.0      # [deg/s] y [deg/s^2] del robot (modo FIRMWARE)
ASENTAR = 0.5                     # [s] ruedas detenidas entre tramos
ALINEAR_EN_BASE = True            # al terminar BASE, girar a 0 grados
CPR_ESPERADO = 905
MODO = "PC"                       # "PC" (recomendado) o "FIRMWARE" (go2point).
# Prueba del 2 nov 2026: go2point termina cada giro ~38 grados antes y cada avance ~5 cm antes
# (cortes de fase por perfil, no por pose medida) y no corrige el rumbo mientras avanza.
# El modo PC cierra el lazo con la pose medida hasta llegar.

# modo PC (control desde esta computadora)
RHO, L = 0.034, 0.1663            # [m] radio de rueda y separacion
TOL_POS = 0.01                    # [m] llegada
TOL_TH = 2.0                      # [deg] fin de giro
K_TH = 2.0                        # [1/s] giro: velocidad del robot = K_TH * error
K_D = 1.0                         # [1/s] avance: v = K_D * distancia que falta
K_RUMBO = 2.0                     # [1/s] correccion de rumbo mientras avanza
W_MIN_RECTA = 30.0                # [deg/s de rueda] zona muerta en linea recta (log del 19 oct: ~25)
W_MIN_GIRO = 45.0                 # [deg/s de rueda] zona muerta al girar (a 30 no se movia) <POR MEDIR>
W_MAX = 150.0                     # [deg/s de rueda]
DT_LENTO = 0.5                    # [s] una respuesta mas lenta que esto -> pausar ruedas
T_SIN_ENLACE = 20.0               # [s] corte de WiFi mas largo que esto -> abortar el tramo

RUTAS = {                         # puntos de o1 en metros: mesas en fila al lado del pasillo (12 nov)
    "MESA1": [(1.0, 0.0)],
    "MESA2": [(2.0, 0.0)],
    "MESA3": [(3.0, 0.0)],
}
LOG = time.strftime("movimiento_%Y%m%d_%H%M%S.csv")
RED = (TimeoutError, ConnectionError, OSError)


def ang(a):
    return (a + 180.0) % 360.0 - 180.0


def lim(v, lo, hi):
    return max(lo, min(hi, v))


def conectar(host, intentos=3):
    """Primera conexion con 5 s de espera y 3 intentos; ya conectado, 1 s para detectar cortes rapido."""
    for i in range(1, intentos + 1):
        print(f"Conectando a {host}:8080 (intento {i}/{intentos}) ...")
        try:
            try:
                r = Robot(host, timeout=5.0)
            except TypeError:                      # versiones viejas de oak9lib sin 'timeout'
                r = Robot(host)
            return r                                # 5 s mientras arranca; iniciar() lo baja a 1 s
        except RED as ex:
            ultimo = ex
            time.sleep(1.0)
    print(f"""
No pude conectarme al robot en {host} ({type(ultimo).__name__}). Revisa en este orden:
  1. La IP: la que muestra la pantalla del robot al encender. Si cambiaste de red, cambia.
  2. Que la laptop este en la MISMA red WiFi que el robot (ipconfig: las 3 primeras partes iguales).
  3. ping {host}   -> si no responde, es la red o la IP.
  4. Test-NetConnection {host} -Port 8080   -> si ping si pero esto no, reinicia el robot.
  5. Que no haya otro programa conectado al robot (cierra main_real.py u otra terminal).""")
    raise SystemExit(1)


class Probador:
    def __init__(self, host):
        self.host = host
        self.r = conectar(host)
        self.visitados = []                # puntos alcanzados desde la base (BASE los recorre al reves)
        self.t_corte, self.n_cortes, self.s_cortes = None, 0, 0.0
        self.sucio = False                 # True tras un timeout: reabrir la conexion antes del siguiente comando
        self.modo = "PC"
        self.tiene_orientation = False
        self.f = open(LOG, "w", newline="")
        self.w = csv.writer(self.f)
        self.w.writerow(["t", "comando", "tramo", "x_obj", "y_obj", "th_obj", "x", "y", "th", "fase", "evento"])
        self.t0 = time.monotonic()

    # ------------------------------------------------------------ comunicacion
    def cmd(self, nombre, **kw):
        """Comando crudo del firmware: funciona aunque la version de oak9lib no tenga el metodo."""
        return self.r._transport.send(nombre, **kw)

    def soporta(self, nombre):
        try:
            return bool(self.cmd(nombre).get("ok"))
        except RED:
            raise
        except Exception:
            return False

    def pose(self):
        p = self.r.pose.get()
        if "x_mm" not in p:                       # respuesta de otro comando (llego tarde): conexion desfasada
            raise TimeoutError(f"respuesta desfasada: {p.get('raw_line')}")
        return p["x_mm"] / 1000.0, p["y_mm"] / 1000.0, p["theta_deg"]

    def ruedas(self, izq, der):
        self.r.wheel_velocity.set(left=round(izq, 1), right=round(der, 1))

    # ------------------------------------------------------------ cortes de WiFi
    # Un timeout NO aborta el tramo: se reconecta (limpia respuestas viejas), se paran las
    # ruedas y se sigue hacia el MISMO punto con la pose del firmware, que sigue contando.
    def _corte(self):
        """Tras un timeout la respuesta tardia podria llegar despues: siempre reabrir la conexion."""
        if self.t_corte is None:
            self.t_corte = time.monotonic()
            self.n_cortes += 1
            print("\n    corte de WiFi: ruedas paradas, reconectando ...", end="", flush=True)
        self.sucio = True
        try:
            self.r._transport.connect()
            self.sucio = False
            self.r.wheel_velocity.stop()
        except RED:
            self.sucio = True
            time.sleep(0.2)

    def _limpiar(self):
        if self.sucio:
            self.r._transport.connect()
            self.sucio = False

    def _fin_corte(self):
        if self.t_corte is not None:
            d = time.monotonic() - self.t_corte
            self.s_cortes += d
            print(f" volvio en {d:.1f} s, sigo")
            self.t_corte = None

    def pose_segura(self):
        """Pose, o None si no hubo respuesta (corte de WiFi)."""
        try:
            self._limpiar()
            p = self.pose()
        except RED:
            self._corte()
            return None
        self._fin_corte()
        return p

    def ruedas_seguras(self, izq, der):
        try:
            self._limpiar()
            if izq == 0 and der == 0:
                self.r.wheel_velocity.stop()
            else:
                self.ruedas(izq, der)
        except RED:
            self._corte()

    def sin_enlace_demasiado(self):
        return self.t_corte is not None and time.monotonic() - self.t_corte > T_SIN_ENLACE

    def pose_espera(self):
        while True:
            p = self.pose_segura()
            if p is not None:
                return p
            if self.sin_enlace_demasiado():
                raise TimeoutError("sin WiFi")
            time.sleep(0.2)

    def transcurrido(self, t_ini):
        """Tiempo del tramo sin contar los cortes de WiFi."""
        en_corte = time.monotonic() - self.t_corte if self.t_corte else 0.0
        return time.monotonic() - t_ini - self.s_cortes - en_corte

    def parar(self):
        for intento in range(3):
            try:
                if self.modo == "FIRMWARE":
                    self.cmd("robot.go2point.stop")
                if self.tiene_orientation:
                    self.cmd("robot.orientation.stop")
                self.r.wheel_velocity.stop()
                return
            except RED:
                time.sleep(0.3)
                try:
                    self.r._transport.connect()
                except OSError:
                    pass
        print("!!! NO SE PUDO MANDAR STOP: apaga el robot con el interruptor !!!")

    def perfil(self):
        if self.modo == "FIRMWARE":
            self.cmd("robot.go2point.pid.set", v_max_giro_deg_s=W_GIRO, a_max_giro_deg_s2=A_GIRO,
                     v_max_avance_mm_s=V_AVANCE * 1000, a_max_avance_mm_s2=A_AVANCE * 1000, ts_ms=25)

    def log(self, cmd, tramo, obj, p, fase="", evento=""):
        self.w.writerow([f"{time.monotonic() - self.t0:.3f}", cmd, tramo, *obj,
                         *(f"{v:.4f}" for v in p), fase, evento])

    # ------------------------------------------------------------ arranque
    def iniciar(self):
        print(f"Conectando a {self.host} ...")
        self.r.wheel_velocity.stop()
        if MODO == "FIRMWARE":
            if self.soporta("robot.go2point.status"):
                self.modo = "FIRMWARE"
            else:
                print("El firmware no responde a go2point: uso el modo PC.")
        self.tiene_orientation = False                # orientation.set: experimental, no confiable
        print(f"Modo de movimiento: {self.modo}"
              + ("  (go2point del firmware)" if self.modo == "FIRMWARE"
                 else "  (lazo cerrado desde la PC con la pose medida y wheel_velocity)"))
        try:
            cpr = self.r.encoder.cpr_get().get("cpr")
            if cpr != CPR_ESPERADO:
                print(f"OJO: el CPR es {cpr}, no {CPR_ESPERADO}. Las distancias van a salir mal.")
        except AttributeError:
            pass
        try:
            print(f"Bateria: {self.r.battery.read().get('voltage')} V")
        except AttributeError:
            pass
        self.cero()
        print("Calibrando giroscopio: NO muevas el robot ...")
        self.espera(15.0)                           # la calibracion tarda unos segundos en responder
        try:
            r = self.cmd("imu.calibrate")
            if not r.get("ok"):
                print(f"  (imu.calibrate no disponible: {r.get('raw_line')})")
        except RED:
            print("  (imu.calibrate no respondio a tiempo; sigo sin recalibrar el giroscopio)")
            self.r._transport.connect()             # descarta una respuesta tardia
        time.sleep(1.0)
        self.espera(5.0)
        self.perfil()
        self.espera(1.0)                            # en movimiento: detectar cortes de WiFi en 1 s
        print(f"Listo. Avance {V_AVANCE} m/s. Registro: {LOG}\n")

    def espera(self, s):
        """Cambia cuanto se espera cada respuesta del robot."""
        self.r._transport.timeout = s
        if self.r._transport._sock is not None:
            self.r._transport._sock.settimeout(s)

    def cero(self):
        self.parar()
        self.r.encoder.reset()                      # encoders PRIMERO, luego la pose
        time.sleep(0.2)
        self.r.pose.set(x_mm=0, y_mm=0, theta_deg=0)
        time.sleep(0.2)
        x, y, th = self.pose()
        ok = abs(x) < 0.005 and abs(y) < 0.005 and abs(th) < 1
        print(f"Pose en cero: ({x:.3f}, {y:.3f}, {th:.1f})  {'OK' if ok else 'NO SE REINICIO, repite CERO'}")
        self.visitados = []

    # ------------------------------------------------------------ fin de tramo
    def terminar_tramo(self, cmd, tramo, obj, t_ini):
        self.parar()                                # limpia la integral del PID entre tramos
        time.sleep(ASENTAR)
        p = self.pose_espera()
        if self.n_cortes:
            print(f"\n  ({self.n_cortes} cortes de WiFi en este tramo, {self.s_cortes:.1f} s en total)", end="")
        if obj[0] != "":
            ex, ey = obj[0] - p[0], obj[1] - p[1]
            print(f"\n  llego a ({p[0]:+.3f}, {p[1]:+.3f}, {p[2]:+.1f})  error ({ex * 1000:+.0f}, {ey * 1000:+.0f}) mm"
                  f" = {math.hypot(ex, ey) * 1000:.0f} mm  en {time.monotonic() - t_ini:.1f} s")
            self.log(cmd, tramo, obj, p, "", f"fin ex={ex:.4f} ey={ey:.4f}")
        else:
            eth = ang(obj[2] - p[2])
            print(f"\n  rumbo final {p[2]:+.1f}  error {eth:+.1f} grados  en {time.monotonic() - t_ini:.1f} s")
            self.log(cmd, tramo, obj, p, "", f"fin eth={eth:.2f}")

    def mostrar(self, fase, p):
        print(f"    {fase:8s} pose=({p[0]:+.3f}, {p[1]:+.3f}, {p[2]:+6.1f})      ", end="\r")

    # ------------------------------------------------------------ primitivas: FIRMWARE
    def ir_fw(self, x, y, cmd, tramo, t_ini, limite):
        resp = self.cmd("robot.go2point.set", x=round(x * 1000, 1), y=round(y * 1000, 1))
        if not resp.get("ok"):
            print(f"  El firmware rechazo el punto: {resp.get('raw_line')}")
            return False
        time.sleep(0.1)
        t_imp = 0.0
        while True:
            try:
                s = self.cmd("robot.go2point.status")
                p = self.pose()
            except RED:
                print("\n  sin respuesta del robot, reintentando ...")
                time.sleep(0.3)
                self.r._transport.connect()
                continue
            self.log(cmd, tramo, (x, y, ""), p, s.get("phase", ""))
            if time.monotonic() - t_imp > 0.25:
                t_imp = time.monotonic()
                self.mostrar(f"fase={s.get('phase')}", p)
            if not s.get("active"):
                return True
            if time.monotonic() - t_ini > limite:
                print(f"\n  TIMEOUT ({limite:.0f} s): el tramo no termino")
                return False
            time.sleep(0.05)

    def girar_fw(self, th, cmd, tramo, t_ini, limite):
        resp = self.cmd("robot.orientation.set", theta=round(th, 2))
        if not resp.get("ok"):
            print(f"  orientation.set rechazado: {resp.get('raw_line')}")
            return False
        quieto = 0
        time.sleep(0.1)
        while True:
            s = self.cmd("robot.orientation.status")
            p = self.pose()
            self.log(cmd, tramo, ("", "", th), p, "giro")
            self.mostrar("giro", p)
            if "active" in s:
                hecho = not s["active"]
            else:
                quieto = quieto + 1 if abs(s.get("error", 99)) <= 1.0 and abs(s.get("wheel_deg_s", 99)) < 1.0 else 0
                hecho = quieto >= 3
            if hecho:
                return True
            if time.monotonic() - t_ini > limite:
                print("\n  TIMEOUT del giro (orientation.set es experimental)")
                return False
            time.sleep(0.05)

    # ------------------------------------------------------------ primitivas: PC
    def girar_pc(self, th, cmd, tramo, t_ini, limite, mostrar_fase="giro"):
        """Gira en su lugar hasta el rumbo th con wheel_velocity (rueda derecha +, izquierda - = antihorario)."""
        t_prev, e_prev = time.monotonic(), None
        while True:
            p = self.pose_segura()
            if p is None:
                if self.sin_enlace_demasiado():
                    print(f"\n  Sin WiFi mas de {T_SIN_ENLACE:.0f} s: tramo abortado")
                    return False
                time.sleep(0.2)
                t_prev = time.monotonic()
                continue
            ahora = time.monotonic()
            dt, t_prev = ahora - t_prev, ahora
            e = ang(th - p[2])
            self.log(cmd, tramo, ("", "", th), p, mostrar_fase)
            self.mostrar(mostrar_fase, p)
            cruzo = e_prev is not None and e * e_prev < 0 and abs(e) < 3 * TOL_TH
            if abs(e) < TOL_TH or cruzo:             # llego, o paso el objetivo (no oscilar en la zona muerta)
                self.ruedas_seguras(0, 0)
                return True
            e_prev = e
            if self.transcurrido(t_ini) > limite:
                print("\n  TIMEOUT del giro: revisa W_MIN_GIRO (zona muerta) o el piso")
                return False
            if dt > DT_LENTO:                        # dato viejo: no girar a ciegas
                self.ruedas_seguras(0, 0)
                continue
            w = (L / (2 * RHO)) * K_TH * e           # deg/s de rueda para q1dot = K_TH * e
            w = math.copysign(lim(abs(w), W_MIN_GIRO, W_MAX), e)
            self.ruedas_seguras(-w, w)
            time.sleep(0.04)

    def ir_pc(self, x, y, cmd, tramo, t_ini, limite):
        """Gira hacia el punto y avanza recto corrigiendo el rumbo, con rampa de aceleracion."""
        p = self.pose_espera()
        if math.hypot(x - p[0], y - p[1]) > TOL_POS:
            rumbo = math.degrees(math.atan2(y - p[1], x - p[0]))
            if not self.girar_pc(rumbo, cmd, tramo, t_ini, limite, "gira"):
                return False
            time.sleep(0.2)
        v_prev, t_prev = 0.0, time.monotonic()
        while True:
            p = self.pose_segura()
            if p is None:
                if self.sin_enlace_demasiado():
                    print(f"\n  Sin WiFi mas de {T_SIN_ENLACE:.0f} s: tramo abortado")
                    return False
                time.sleep(0.2)
                v_prev, t_prev = 0.0, time.monotonic()      # al volver arranca otra vez con rampa
                continue
            ahora = time.monotonic()
            dt, t_prev = ahora - t_prev, ahora
            dx, dy = x - p[0], y - p[1]
            th = math.radians(p[2])
            ed = dx * math.cos(th) + dy * math.sin(th)          # lo que falta en la direccion de avance
            self.log(cmd, tramo, (x, y, ""), p, "avanza")
            self.mostrar("avanza", p)
            if ed < TOL_POS:                                    # llego (o ya lo paso)
                self.ruedas_seguras(0, 0)
                return True
            if self.transcurrido(t_ini) > limite:
                print(f"\n  TIMEOUT ({limite:.0f} s): el tramo no termino")
                return False
            if dt > DT_LENTO:
                self.ruedas_seguras(0, 0)
                v_prev = 0.0
                continue
            v = min(K_D * ed, V_AVANCE, v_prev + A_AVANCE * dt)  # rampa de aceleracion
            v_prev = v
            e_rumbo = ang(math.degrees(math.atan2(dy, dx)) - p[2]) if math.hypot(dx, dy) > 0.05 else 0.0
            base = math.degrees(v / RHO)                         # deg/s de rueda
            base = max(base, W_MIN_RECTA)
            corr = (L / (2 * RHO)) * K_RUMBO * e_rumbo
            corr = lim(corr, -0.5 * base, 0.5 * base)
            self.ruedas_seguras(base - corr, base + corr)
            time.sleep(0.04)

    # ------------------------------------------------------------ primitivas comunes
    def ir(self, x, y, cmd, tramo):
        self.t_corte, self.n_cortes, self.s_cortes = None, 0, 0.0
        x0, y0, _ = self.pose_espera()
        d = math.hypot(x - x0, y - y0)
        limite = d / V_AVANCE + 180 / W_GIRO + 20.0
        print(f"  tramo {tramo}: IR({x:.2f}, {y:.2f})  distancia {d:.2f} m")
        t_ini = time.monotonic()
        f = self.ir_fw if self.modo == "FIRMWARE" else self.ir_pc
        ok = f(x, y, cmd, tramo, t_ini, limite)
        if not ok:
            self.parar()
            return False
        self.terminar_tramo(cmd, tramo, (x, y, ""), t_ini)
        return True

    def girar(self, th, cmd, tramo):
        self.t_corte, self.n_cortes, self.s_cortes = None, 0, 0.0
        p = self.pose_espera()
        print(f"  tramo {tramo}: GIRAR({th:.0f})  desde {p[2]:.1f}")
        limite = abs(ang(th - p[2])) / 30.0 + 15.0
        t_ini = time.monotonic()
        f = self.girar_fw if self.tiene_orientation else self.girar_pc
        if not f(th, cmd, tramo, t_ini, limite):
            self.parar()
            return False
        self.terminar_tramo(cmd, tramo, ("", "", th), t_ini)
        return True

    # ------------------------------------------------------------ comandos
    def mesa(self, nombre):
        if self.visitados:
            print("El robot no esta en la base. Escribe BASE primero.")
            return
        x, y, _ = self.pose()
        if math.hypot(x, y) > 0.05:
            print(f"Ojo: el robot cree que esta a {math.hypot(x, y) * 100:.0f} cm de la base.")
        print(f"{nombre}: {RUTAS[nombre]}")
        t = time.monotonic()
        for i, (px, py) in enumerate(RUTAS[nombre], start=1):
            if not self.ir(px, py, nombre, f"{i}/{len(RUTAS[nombre])}"):
                print("Recorrido interrumpido. Escribe BASE para regresar.")
                return
            self.visitados.append((px, py))
        print(f"{nombre} completa en {time.monotonic() - t:.1f} s. MIDE la posicion real: <POR MEDIR>\n")

    def base(self):
        x, y, _ = self.pose()
        puntos = list(reversed(self.visitados)) + [(0.0, 0.0)]
        while len(puntos) > 1 and math.hypot(puntos[0][0] - x, puntos[0][1] - y) < 0.05:
            puntos.pop(0)                           # ya esta en ese punto
        n = len(puntos) + (1 if ALINEAR_EN_BASE else 0)
        print(f"BASE: {puntos}" + ("  + GIRAR(0)" if ALINEAR_EN_BASE else ""))
        t = time.monotonic()
        for i, (px, py) in enumerate(puntos, start=1):
            if not self.ir(px, py, "BASE", f"{i}/{n}"):
                print("Regreso interrumpido. Escribe BASE otra vez para continuar.")
                return
            if self.visitados and (px, py) == self.visitados[-1]:
                self.visitados.pop()
        self.visitados = []
        if ALINEAR_EN_BASE:
            self.girar(0.0, "BASE", f"{n}/{n}")
        print(f"En base en {time.monotonic() - t:.1f} s.\n")

    def ejecutar(self, linea):
        global V_AVANCE
        partes = linea.strip().upper().split()
        if not partes:
            return True
        cmd = "".join(partes) if partes[0] == "MESA" else partes[0]
        try:
            if cmd in RUTAS:
                self.mesa(cmd)
            elif cmd == "BASE":
                self.base()
            elif cmd == "IR" and len(partes) == 3:
                px, py = float(partes[1]), float(partes[2])
                if self.ir(px, py, "IR", "1/1"):
                    self.visitados.append((px, py))
            elif cmd == "GIRAR" and len(partes) == 2:
                self.girar(float(partes[1]), "GIRAR", "1/1")
            elif cmd == "POSE":
                x, y, th = self.pose()
                print(f"pose = ({x:+.3f} m, {y:+.3f} m, {th:+.1f} grados)")
            elif cmd == "CERO":
                self.cero()
            elif cmd == "VEL" and len(partes) == 2:
                V_AVANCE = lim(float(partes[1]), 0.03, 0.25)
                self.perfil()
                print(f"Avance a {V_AVANCE} m/s")
            elif cmd == "SALIR":
                return False
            else:
                print("No entendi. Comandos: MESA1 MESA2 MESA3 BASE  IR x y  GIRAR th  POSE  CERO  VEL v  SALIR")
        except KeyboardInterrupt:
            self.parar()
            print("\n*** PARO (Ctrl+C) ***  Escribe BASE para regresar o POSE para ver donde quedo.")
        except RED as ex:
            self.parar()
            print(f"\nError de comunicacion ({type(ex).__name__}). Robot detenido; reintenta el comando.")
            try:
                self.r._transport.connect()
            except OSError:
                pass
        except ValueError:
            print("Numero invalido.")
        return True

    def cerrar(self):
        try:
            self.parar()
        finally:
            self.f.close()
            self.r.close()
            print(f"Robot detenido. Registro en {LOG}")


def main():
    p = Probador(sys.argv[1] if len(sys.argv) > 1 else HOST)
    try:
        p.iniciar()
        print("Comandos: MESA1 MESA2 MESA3 BASE  IR x y  GIRAR th  POSE  CERO  VEL v  SALIR   (Ctrl+C = paro)")
        while True:
            try:
                linea = input("oak9> ")
            except EOFError:
                break
            except KeyboardInterrupt:
                print()
                continue
            if not p.ejecutar(linea):
                break
    finally:
        p.cerrar()


if __name__ == "__main__":
    main()
