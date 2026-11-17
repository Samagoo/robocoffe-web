"""Adaptador del OAK9 real (oak9lib, TCP al ESP32-S3) para la maquina de estados.

Movimiento: NavegadorPC (movimiento.py), el MISMO lazo cerrado que corre en Webots. En cada
ciclo lee la pose (pose.get: o1 en mm y grados, encoders + giroscopio del firmware) y manda
velocidades de rueda (wheel_velocity, deg/s) hasta llegar al punto o al rumbo.
No usa go2point: en la prueba del 2 nov 2026 termino cada giro ~38 grados antes y cada avance
~5 cm antes, y no corrige el rumbo al avanzar (ver diagnostico_movimiento_2nov.png).
Si una lectura tarda mas de 0.5 s (WiFi), el navegador pone las ruedas en cero.
Cualquier error de red regresa None (sin respuesta): la maquina decide (DETENIDO por ENLACE).
Solo usa comandos que ya funcionaron con la oak9lib del equipo: wheel_velocity, pose, encoder,
battery; los demas (imu.calibrate, cpr, ultrasonicos, indicadores) son opcionales.
"""
import time

from oak9 import Robot

from .movimiento import EN_CURSO, TERMINADO, NavegadorPC

CPR_ESPERADO = 905                 # calibrado el 6 de octubre de 2026
FRONTALES = ("s1",)                # <RELLENAR>: claves de ultrasonico que miran al frente
ERRORES_RED = (TimeoutError, ConnectionError, OSError)


class RobotOAK9:
    def __init__(self, host, cfg, port=8080, timeout=1.0, nav=None):
        self.host, self.cfg, self.port, self.timeout = host, cfg, port, timeout
        self.nav = nav or NavegadorPC(v_avance=cfg.v_avance)
        self.r = None
        self.pose_ult = (0.0, 0.0, 0.0)
        self.t_bat, self.bat = -1e9, None
        self.t_us, self.dist = -1e9, None
        self._t_reconexion, self._espera = 0.0, 0.5
        self._parado = True

    # ------------------------------------------------------------ conexion
    def _conectar(self):
        if self.r is None:
            try:
                self.r = Robot(self.host, port=self.port, timeout=5.0)   # conexion paciente
            except TypeError:                        # oak9lib viejas sin port/timeout
                self.r = Robot(self.host)
            self._timeout_resp(self.timeout)
        return self.r

    def _timeout_resp(self, seg):
        """Cuanto se espera cada respuesta del robot."""
        t = self.r._transport
        t.timeout = seg
        if t._sock is not None:
            t._sock.settimeout(seg)

    def _caida(self, t):
        """Cierra y programa la reconexion con espera creciente (0.5, 1, 2 s)."""
        try:
            if self.r is not None:
                self.r.close()
        except Exception:
            pass
        self.r = None
        self._t_reconexion = t + self._espera
        self._espera = min(self._espera * 2, 2.0)

    def _cmd(self, nombre, **kw):
        """Comando crudo del firmware (funciona aunque la version de oak9lib no tenga el metodo)."""
        return self._conectar()._transport.send(nombre, **kw)

    def _ruedas(self, izq, der):
        r = self._conectar()
        if izq == 0.0 and der == 0.0:
            if not self._parado:
                r.wheel_velocity.stop()
                self._parado = True
            return
        r.wheel_velocity.set(left=round(izq, 1), right=round(der, 1))
        self._parado = False

    # ------------------------------------------------------------ interfaz
    def verificar_inicio(self, t=0.0):
        try:
            r = self._conectar()
            r.wheel_velocity.stop()
            self._parado = True
            self.nav.detener()
            try:
                cpr = r.encoder.cpr_get().get("cpr")
                if cpr is not None and cpr != CPR_ESPERADO:
                    return False, f"cpr={cpr}_esperado={CPR_ESPERADO}"
            except AttributeError:
                pass
            r.encoder.reset()                                     # encoders PRIMERO
            time.sleep(0.2)
            r.pose.set(x_mm=0, y_mm=0, theta_deg=0)
            time.sleep(0.2)
            p = r.pose.get()
            if abs(p["x_mm"]) > 5 or abs(p["y_mm"]) > 5 or abs(p["theta_deg"]) > 1:
                return False, "pose_no_reinicia"
            self._timeout_resp(15.0)                                    # la calibracion tarda en responder
            try:
                self._cmd("imu.calibrate")                        # robot QUIETO; opcional
            except ERRORES_RED:
                r._transport.connect()                            # descarta la respuesta tardia
            self._timeout_resp(5.0)
            try:
                self.bat = r.battery.read().get("voltage")
            except AttributeError:
                self.bat = None
            c = self.cfg
            if c.bat_min is not None and (self.bat is None or self.bat < c.bat_min):
                return False, f"bateria={self.bat}"
            self._timeout_resp(self.timeout)                            # en operacion: detectar cortes rapido
            return True, f"navegador_pc_bat={self.bat}"
        except ERRORES_RED as ex:
            self._caida(t)
            return False, f"sin_conexion_{type(ex).__name__}"

    def leer(self, t):
        if self.r is None and t < self._t_reconexion:
            return None
        try:
            r = self._conectar()
            p = r.pose.get()
            if not p.get("ok", True):
                return None
            pose = (p["x_mm"] / 1000.0, p["y_mm"] / 1000.0, p["theta_deg"])
            self.pose_ult = pose
            if self.nav.activo:
                izq, der, _ = self.nav.paso(pose, t)
                self._ruedas(izq, der)
            if t - self.t_us >= 0.1:                              # 10 Hz, si existe
                try:
                    us = r.ultrasonic.read()
                    vals = [us.get(k) for k in FRONTALES if isinstance(us.get(k), (int, float)) and us.get(k) > 0]
                    self.dist = min(vals) / 1000.0 if vals else None
                except AttributeError:
                    self.dist = None
                self.t_us = t
            if t - self.t_bat >= 5.0:
                try:
                    self.bat = r.battery.read().get("voltage")
                except AttributeError:
                    pass
                self.t_bat = t
            self._espera = 0.5
            return {"pose": pose, "nav": EN_CURSO if self.nav.activo else TERMINADO,
                    "dist_frontal": self.dist, "bateria": self.bat}
        except ERRORES_RED:
            self._caida(t)
            return None

    def iniciar_tramo(self, tramo, t):
        """True = aceptado. El movimiento lo hace leer() en cada ciclo."""
        self.nav.iniciar(tramo, self.pose_ult, t)
        return True

    def detener(self, t):
        self.nav.detener()
        for intento in range(3):
            try:
                self._conectar().wheel_velocity.stop()
                self._parado = True
                return True
            except ERRORES_RED:
                self._caida(t)
                time.sleep(0.2)
        print("[OAK9] !!! NO SE PUDO MANDAR STOP: apaga el robot con el interruptor !!!")
        return False

    def indicar(self, texto, t=0.0):
        try:
            r = self._conectar()
            r.indicators.lcd_print(row=0, col=0, text=texto.replace(" ", "_")[:16])
            if texto.startswith("ERROR"):
                r.indicators.tone(hz=440, ms=800)
            elif texto.startswith("MESA") or texto == "LISTO":
                r.indicators.tone(hz=1200, ms=120)
        except Exception:
            pass                      # indicar nunca debe tumbar la maquina
