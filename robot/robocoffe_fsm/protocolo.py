"""Protocolo de lineas (seccion 7): 'COMANDO clave=valor ...\\n'.

Mismo estilo que el firmware del OAK9 ('OK <cmd> k=v' / 'ERROR <cmd> CODIGO').
"""
from dataclasses import dataclass, field

COMANDOS = {"ORDEN", "CANCELAR", "PAUSA", "REANUDAR", "RESET", "ESTADO", "PING", "RETIRADO"}
DESTINOS = {"MESA1": 1, "MESA2": 2, "MESA3": 3}
CONSULTAS = {"ESTADO", "PING"}          # se responden siempre, no cambian el estado


@dataclass
class Mensaje:
    cmd: str
    id: int
    campos: dict = field(default_factory=dict)


class ErrorFormato(ValueError):
    pass


def parsear(linea):
    """'ORDEN id=17 destino=MESA1' -> Mensaje. Lanza ErrorFormato si no es valido."""
    tokens = linea.strip().split()
    if not tokens:
        raise ErrorFormato("linea vacia")
    cmd = tokens[0].upper()
    if cmd not in COMANDOS:
        raise ErrorFormato(f"comando desconocido {tokens[0]!r}")
    campos = {}
    for tok in tokens[1:]:
        if "=" not in tok:
            raise ErrorFormato(f"campo sin '=': {tok!r}")
        k, _, v = tok.partition("=")
        campos[k.lower()] = v
    try:
        mid = int(campos.pop("id"))
    except (KeyError, ValueError):
        raise ErrorFormato("falta id entero")
    if cmd == "ORDEN":
        destino = campos.get("destino", "").upper()
        if not destino:
            raise ErrorFormato("ORDEN sin destino")
        campos["destino"] = destino
    return Mensaje(cmd, mid, campos)


def ok(cmd, mid, **kv):
    return " ".join([f"OK {cmd} id={mid}"] + [f"{k}={v}" for k, v in kv.items()])


def error(cmd, mid, motivo):
    return f"ERROR {cmd} id={mid} {motivo}"


def evento(nombre, **kv):
    return " ".join([f"EVT {nombre}"] + [f"{k}={v}" for k, v in kv.items()])
