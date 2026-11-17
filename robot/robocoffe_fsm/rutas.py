"""Rutas como datos (seccion 5). Marco de la base: x al frente, y a la izquierda, metros.

Disposicion del 12 nov 2026: tres mesas en fila, una detras de la otra, al lado del pasillo.
El robot avanza en linea recta y se detiene junto a cada mesa (o1 en x = 1, 2 o 3 m, y = 0);
las mesas quedan a su derecha (centro en y = -Y_MESA). Ver webots/worlds/oak9_entregas.wbt.

Cada ruta es una lista de tramos. Agregar una mesa = agregar un renglon a RUTAS
(y su nombre en protocolo.DESTINOS / fsm.ESTADO_DE_DESTINO).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Tramo:
    tipo: str            # "IR" (ir al punto x, y) o "GIRAR" (rumbo absoluto th)
    x: float = 0.0
    y: float = 0.0
    th: float = 0.0      # [deg], solo GIRAR
    reversa: bool = False  # IR en reversa: llega de espaldas, sin girar 180 grados

    def __str__(self):
        if self.tipo == "GIRAR":
            return f"GIRAR({self.th:.0f})"
        return f"IR({self.x:.2f}, {self.y:.2f}{', reversa' if self.reversa else ''})"


def IR(x, y, reversa=False):
    return Tramo("IR", x, y, reversa=reversa)


def GIRAR(th):
    return Tramo("GIRAR", th=th)


BASE = IR(0.0, 0.0)

# Mesas en fila al lado del pasillo: el robot se detiene a su lado
D_MESAS = {1: 1.0, 2: 2.0, 3: 3.0}         # [m] distancia de la base al punto de entrega
RUTAS = {m: [IR(d, 0.0)] for m, d in D_MESAS.items()}


def ruta_regreso(ruta, k, reversa=False):
    """Ruta de vuelta a la base por los mismos puntos: los puntos ruta[:k] al reves, la base y GIRAR(0).

    Sirve igual al llegar a la mesa (el robot esta en ruta[k]) y al CANCELAR a medio
    tramo k (el robot esta entre ruta[k-1] y ruta[k]): en ambos casos el siguiente
    punto seguro es ruta[k-1], que ya se recorrio.
    reversa=True: regresa de espaldas (sin los dos giros de 180 grados); util cuando la ruta
    es una linea recta, como en la disposicion de mesas en fila.
    """
    puntos = [IR(t.x, t.y, reversa) for t in ruta[:k] if t.tipo == "IR"]
    return list(reversed(puntos)) + [IR(0.0, 0.0, reversa), GIRAR(0.0)]
