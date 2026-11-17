"""Una prueba por renglon de la tabla de transiciones (T1-T17) y por regla del protocolo.

    python -m pytest -q tests
Usa el robot simulado y un reloj simulado: las 30+ misiones corren en segundos.
"""
import pytest

from robocoffe_fsm import fsm as F
from robocoffe_fsm.canales import CanalMemoria
from robocoffe_fsm.config import Config
from robocoffe_fsm.ejecutor import Ejecutor, RelojSimulado
from robocoffe_fsm.robot_sim import RobotSimulado


class Banco:
    def __init__(self, cfg=None, **robot_kw):
        self.cfg = cfg or Config()
        self.reloj = RelojSimulado()
        self.robot = RobotSimulado(**robot_kw)
        self.canal = CanalMemoria()
        self.ej = Ejecutor(F.MaquinaEntrega(self.cfg), self.robot, self.canal,
                           reloj=self.reloj, dormir=self.reloj.dormir, log=lambda l: None)
        self.fsm = self.ej.fsm

    def paso(self, n=1):
        for _ in range(n):
            self.ej.ciclo()
            self.reloj.dormir(self.cfg.periodo)

    def hasta(self, cond, limite=300.0):
        t_lim = self.reloj.t + limite
        while not cond(self.fsm) and self.reloj.t < t_lim:
            self.paso()
        assert cond(self.fsm), f"no se cumplio; estado={self.fsm.estado} t={self.reloj.t:.1f}"

    def mandar(self, linea):
        self.canal.entrada.append(linea)
        self.paso()

    def en(self, estado):
        return lambda f: f.estado == estado

    def secuencia(self):
        return [(a, b) for _, a, b, _ in self.fsm.historial]

    def respuestas(self, prefijo):
        return [l for l in self.canal.salida if l.startswith(prefijo)]


def listo(**kw):
    b = Banco(**kw)
    b.hasta(b.en(F.ESPERANDO_ORDEN))
    return b


# ------------------------------------------------------------------ T1, T2
def test_T1_inicializa_y_espera():
    b = listo()
    assert b.secuencia()[:2] == [(None, F.INICIALIZANDO), (F.INICIALIZANDO, F.ESPERANDO_ORDEN)]


def test_T2_falla_de_inicio_va_a_error():
    b = Banco(init_ok=False)
    b.hasta(b.en(F.ERROR))
    assert b.fsm.codigo_error == "E_INIT"


# ------------------------------------------------------------------ T3-T5, T7, T9-T11: las tres mesas
@pytest.mark.parametrize("mesa,destino_final,tramos_ida", [
    ("MESA1", (1.0, 0.0), 1), ("MESA2", (2.0, 0.0), 1), ("MESA3", (3.0, 0.0), 1)])
def test_mision_completa(mesa, destino_final, tramos_ida):
    b = listo()
    b.mandar(f"ORDEN id=1 destino={mesa}")
    rec = F.ESTADO_DE_DESTINO[int(mesa[-1])]
    assert b.fsm.estado == rec
    b.hasta(b.en(F.EN_MESA))
    assert (round(b.robot.x, 3), round(b.robot.y, 3)) == destino_final
    b.hasta(b.en(F.ESPERANDO_ORDEN))
    assert (round(b.robot.x, 3), round(b.robot.y, 3), round(b.robot.th, 1)) == (0.0, 0.0, 0.0)
    estados = [a for a, _ in b.secuencia()][2:] + [b.fsm.estado]
    assert estados == [F.ESPERANDO_ORDEN, rec, F.EN_MESA, F.REGRESO_BASE, F.ESPERANDO_ORDEN]
    tramos_ok = [l for l in b.canal.salida if l.startswith("EVT TRAMO") and "ok=True" in l]
    assert len(tramos_ok) == tramos_ida + tramos_ida + 1        # ida + regreso (puntos + base) + giro


def test_T10_vaso_retirado_adelanta_el_regreso():
    b = listo()
    b.ej.fuente_vaso = lambda: b.fsm.estado == F.EN_MESA
    b.mandar("ORDEN id=1 destino=MESA1")
    b.hasta(b.en(F.EN_MESA))
    t0 = b.reloj.t
    b.hasta(b.en(F.REGRESO_BASE))
    assert b.reloj.t - t0 < 0.2 and b.fsm.historial[-1][3] == "vaso_retirado"


# ------------------------------------------------------------------ T6 y reglas del protocolo
def test_T6_orden_invalida_y_destino_desconocido():
    b = listo()
    b.mandar("ORDEN id=1 destino=MESA9")
    b.mandar("VOLAR id=2")
    b.mandar("ORDEN destino=MESA1")
    assert b.fsm.estado == F.ESPERANDO_ORDEN
    assert b.respuestas("ERROR ORDEN id=1 DESTINO_INVALIDO")
    assert len(b.respuestas("ERROR ? id=- FORMATO")) == 2


def test_T6_fuera_de_base():
    b = listo()
    b.robot.x = 0.20
    b.paso(2)
    b.mandar("ORDEN id=1 destino=MESA1")
    assert b.respuestas("ERROR ORDEN id=1 FUERA_DE_BASE") and b.fsm.estado == F.ESPERANDO_ORDEN


def test_orden_ocupado_e_idempotencia():
    b = listo()
    b.mandar("ORDEN id=5 destino=MESA1")
    b.mandar("ORDEN id=5 destino=MESA1")           # reintento: misma respuesta, sin otra mision
    b.mandar("ORDEN id=6 destino=MESA2")           # ocupado
    b.mandar("ORDEN id=4 destino=MESA3")           # id viejo
    assert len(b.respuestas("OK ORDEN id=5")) == 2
    assert b.respuestas("ERROR ORDEN id=6 OCUPADO")
    assert b.respuestas("ERROR ORDEN id=4 ID_REPETIDO")
    assert b.fsm.estado == F.RECORRIDO_MESA_1


def test_consultas_siempre_responden():
    b = listo()
    b.mandar("ORDEN id=1 destino=MESA3")
    b.mandar("ESTADO id=2")
    b.mandar("PING id=3")
    assert b.respuestas("OK ESTADO id=2 estado=RECORRIDO_MESA_3")
    assert b.respuestas("OK PING id=3 estado=RECORRIDO_MESA_3")


def test_perder_bluetooth_no_cambia_nada():
    b = listo()
    b.mandar("ORDEN id=1 destino=MESA1")
    b.ej.canal = None                               # el canal de ordenes desaparece
    b.hasta(b.en(F.ESPERANDO_ORDEN))
    assert F.DETENIDO not in [a for _, a in b.secuencia()]


# ------------------------------------------------------------------ T8 reintento, T14 E_POSICION
def test_T8_reintento_corrige_tramo_corto():
    b = listo(corto=0.02)                          # cada tramo se queda 2 % corto (6 cm en 3 m)
    b.mandar("ORDEN id=1 destino=MESA3")
    b.hasta(b.en(F.EN_MESA))
    assert any("reintentos=0 ok=False" in l for l in b.canal.salida)
    assert abs(b.robot.x - 3.0) <= b.cfg.tol_pos


def test_T14_error_de_posicion_tras_reintentos():
    cfg = Config(tol_pos=0.001)
    b = listo(cfg=cfg, corto=0.5)                  # nunca llega: cada intento hace la mitad
    b.mandar("ORDEN id=1 destino=MESA1")
    b.hasta(b.en(F.ERROR))
    assert b.fsm.codigo_error == "E_POSICION"


# ------------------------------------------------------------------ T12 cancelar
def test_T12_cancelar_regresa_por_los_puntos_alcanzados():
    b = listo()
    b.mandar("ORDEN id=1 destino=MESA3")
    b.hasta(lambda f: f.pose[0] > 1.5)
    b.mandar("CANCELAR id=2 orden=99")              # orden equivocada: se rechaza
    assert b.respuestas("ERROR CANCELAR id=2 ORDEN_NO_COINCIDE")
    b.mandar("CANCELAR id=3 orden=1")
    assert b.fsm.estado == F.REGRESO_BASE
    assert [str(t) for t in b.fsm.ruta] == ["IR(0.00, 0.00)", "GIRAR(0)"]
    b.hasta(b.en(F.ESPERANDO_ORDEN))
    assert abs(b.robot.x) < 1e-3 and abs(b.robot.y) < 1e-3


def test_cancelar_no_permitido_en_regreso():
    b = listo()
    b.mandar("ORDEN id=1 destino=MESA1")
    b.hasta(b.en(F.REGRESO_BASE))
    b.mandar("CANCELAR id=2 orden=1")
    assert b.respuestas("ERROR CANCELAR id=2 NO_PERMITIDO")


# ------------------------------------------------------------------ T13 / T15 detenido y reanuda
def test_T13_T15_obstaculo_detiene_y_reanuda_sin_recorrer_de_mas():
    b = listo(obstaculos=[(5.0, 9.0, 0.10)])
    b.mandar("ORDEN id=1 destino=MESA1")
    b.hasta(b.en(F.DETENIDO))
    assert b.fsm.causa == "OBSTACULO"
    x_paro = b.robot.x
    b.hasta(b.en(F.RECORRIDO_MESA_1))
    assert b.reloj.t >= 9.0 + b.cfg.t_despeje - 0.1
    b.hasta(b.en(F.EN_MESA))
    assert b.robot.recorrido == pytest.approx(1.0, abs=1e-3)   # reanudar no vuelve a contar el tramo
    assert 0 < x_paro < 1.0


def test_T13_T15_corte_de_enlace():
    b = listo(cortes=[(4.0, 6.0)])
    b.mandar("ORDEN id=1 destino=MESA1")
    b.hasta(b.en(F.DETENIDO))
    assert b.fsm.causa == "ENLACE"
    b.hasta(b.en(F.ESPERANDO_ORDEN))
    assert abs(b.robot.x) < 1e-3


def test_T13_T15_pausa_y_reanudar():
    b = listo()
    b.mandar("ORDEN id=1 destino=MESA1")
    b.paso(40)
    b.mandar("PAUSA id=2")
    assert b.fsm.estado == F.DETENIDO
    b.paso(int(b.cfg.t_max_detenido / b.cfg.periodo) + 20)      # la pausa no expira
    assert b.fsm.estado == F.DETENIDO
    b.mandar("REANUDAR id=3")
    b.paso(2)
    assert b.fsm.estado == F.RECORRIDO_MESA_1


def test_T13_atasco_y_T16_segundo_atasco():
    b = listo(atascos=[(3.0, 200.0)])               # ruedas trabadas despues de 3 s
    b.mandar("ORDEN id=1 destino=MESA1")
    b.hasta(b.en(F.DETENIDO))
    assert b.fsm.causa == "ATASCO"
    b.hasta(b.en(F.ERROR))
    assert b.fsm.codigo_error == "E_ATASCO"


def test_T16_detenido_demasiado_tiempo():
    b = listo(obstaculos=[(5.0, 500.0, 0.10)])
    b.mandar("ORDEN id=1 destino=MESA1")
    b.hasta(b.en(F.ERROR), limite=100)
    assert b.fsm.codigo_error == "E_DETENIDO_TIMEOUT"


# ------------------------------------------------------------------ T14 otras causas
def test_T14_firmware_rechaza_tramo():
    b = listo(rechazar_en=0)
    b.mandar("ORDEN id=1 destino=MESA2")
    b.hasta(b.en(F.ERROR))
    assert b.fsm.codigo_error == "E_TRAMO_RECHAZADO"


def test_T14_salto_de_pose():
    b = listo(salto_en=5.0)
    b.mandar("ORDEN id=1 destino=MESA1")
    b.hasta(b.en(F.ERROR))
    assert b.fsm.codigo_error == "E_SALTO_POSE"


def test_T14_timeout_de_tramo():
    cfg = Config(margen_tramo=-12.0)                # T_MAX_TRAMO menor que lo que tarda
    b = listo(cfg=cfg)
    b.mandar("ORDEN id=1 destino=MESA1")
    b.hasta(b.en(F.ERROR))
    assert b.fsm.codigo_error == "E_TRAMO_TIMEOUT"


# ------------------------------------------------------------------ T17 reset
def test_T17_reset_desde_error_y_ordenes_rechazadas_en_error():
    b = listo(rechazar_en=0)
    b.mandar("ORDEN id=1 destino=MESA1")
    b.hasta(b.en(F.ERROR))
    b.mandar("ORDEN id=2 destino=MESA1")
    assert b.respuestas("ERROR ORDEN id=2 EN_ERROR")
    b.robot.rechazar_en = None
    b.mandar("RESET id=3")
    b.hasta(b.en(F.ESPERANDO_ORDEN))
    b.mandar("ORDEN id=4 destino=MESA1")
    b.hasta(b.en(F.EN_MESA))


# ------------------------------------------------------------------ repetibilidad logica
def test_treinta_misiones_seguidas_vuelven_a_base():
    b = listo()
    for i in range(30):
        b.mandar(f"ORDEN id={i + 1} destino=MESA{i % 3 + 1}")
        b.hasta(b.en(F.ESPERANDO_ORDEN))
    assert abs(b.robot.x) < 1e-6 and abs(b.robot.y) < 1e-6 and abs(b.robot.th) < 1e-6
    assert F.ERROR not in [a for _, a in b.secuencia()]


# ------------------------------------------------------------------ regreso en reversa
def test_regreso_en_reversa_sin_giros():
    b = listo(cfg=Config(regreso_en_reversa=True))
    b.mandar("ORDEN id=1 destino=MESA3")
    rumbos = []
    while b.fsm.estado != F.ESPERANDO_ORDEN or not rumbos:
        b.paso()
        rumbos.append(b.robot.th)
    assert max(abs(r) for r in rumbos) < 1e-6          # nunca giro
    assert abs(b.robot.x) < 1e-3 and abs(b.robot.y) < 1e-3


def test_T10_orden_retirado_por_tcp():
    b = listo()
    b.mandar("RETIRADO id=1")                         # fuera de EN_MESA: no permitido
    assert b.respuestas("ERROR RETIRADO id=1 NO_PERMITIDO")
    b.mandar("ORDEN id=2 destino=MESA1")
    b.hasta(b.en(F.EN_MESA))
    b.mandar("RETIRADO id=3")
    assert b.respuestas("OK RETIRADO id=3 estado=REGRESO_BASE")
    assert b.fsm.estado == F.REGRESO_BASE and b.fsm.historial[-1][3] == "vaso_retirado"
