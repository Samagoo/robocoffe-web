"""Parametros de la maquina de estados (seccion 4 del documento de diseno).

Los valores marcados <POR MEDIR> o <RELLENAR> son propuestas: se ajustan
con la calibracion (seccion 9) o los decide el equipo.
"""
from dataclasses import dataclass, field


@dataclass
class Config:
    periodo: float = 0.05            # [s] lazo a 20 Hz
    tol_pos: float = 0.03            # [m] tolerancia de llegada     <RELLENAR> tras validar
    tol_th: float = 3.0              # [deg] tolerancia de rumbo
    n_reintentos: int = 2            # reintentos por tramo
    t_asentar: float = 0.5           # [s] stop + pausa entre tramos
    margen_tramo: float = 10.0       # [s] T_MAX_TRAMO = d/v + dth/w + margen
    v_avance: float = 0.10           # [m/s] velocidad de avance del navegador (empieza lento)
    a_avance: float = 0.10           # [m/s^2]
    w_giro: float = 90.0             # [deg/s]
    a_giro: float = 120.0            # [deg/s^2]
    d_obst: float = 0.25             # [m] obstaculo frontal          <POR MEDIR>
    t_despeje: float = 2.0           # [s] causa ausente antes de reanudar
    t_max_detenido: float = 30.0     # [s]                            <RELLENAR>
    t_enlace: float = 1.0            # [s] sin respuesta del robot -> DETENIDO
    t_atasco: float = 3.0            # [s] sin avanzar d_atasco ni girar th_atasco
    d_atasco: float = 0.005          # [m]
    th_atasco: float = 2.0           # [deg]
    t_entrega: float = 10.0          # [s] espera en la mesa          <RELLENAR>
    t_init: float = 15.0             # [s]
    bat_min: float = None            # [V] para despachar   <POR MEDIR> (None = sin verificar)
    bat_crit: float = None           # [V] minimo de operacion <POR MEDIR>
    base_tol_pos: float = 0.05       # [m] "esta en la base" para aceptar una orden
    base_tol_th: float = 5.0         # [deg]
    t_latido: float = 1.0            # [s] periodo de EVT LATIDO
    salto_margen: float = 0.02       # [m] margen del detector de saltos de pose
    regreso_en_reversa: bool = False # True: regresar de espaldas (sin los dos giros de 180 grados)
