"""Lado de la plataforma: manda la orden por WiFi (TCP), reintenta y sigue la telemetria.

    python enviar_orden.py --host <ip de la computadora de la maquina> MESA2
    python enviar_orden.py MESA1                       # misma computadora (127.0.0.1:9000)

Reglas del protocolo (seccion 7.2): id creciente, reintento con el MISMO id si no hay
respuesta en 2 s (hasta 3 veces), se termina al ver EN_BASE o ERROR.
"""
import argparse
import socket
import time


def abrir(a):
    if a.canal == "serie":
        import serial
        s = serial.Serial(a.puerto, a.baud, timeout=0.1)
        return (lambda l: s.write((l + "\n").encode())), (lambda: s.readline().decode(errors="replace").strip())
    c = socket.create_connection((a.host, int(a.puerto)), timeout=0.1)
    buf = [""]

    def leer():
        try:
            buf[0] += c.recv(4096).decode(errors="replace")
        except socket.timeout:
            pass
        if "\n" in buf[0]:
            l, _, buf[0] = buf[0].partition("\n")
            return l.strip()
        return ""
    return (lambda l: c.sendall((l + "\n").encode())), leer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("destino", choices=["MESA1", "MESA2", "MESA3"])
    ap.add_argument("--canal", choices=["tcp", "serie"], default="tcp")
    ap.add_argument("--puerto", default="9000")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--baud", type=int, default=9600)
    a = ap.parse_args()
    enviar, leer = abrir(a)
    oid = int(time.time() * 10)                         # decimas de segundo: creciente entre sesiones y entre herramientas
    for intento in range(3):
        enviar(f"ORDEN id={oid} destino={a.destino}")
        t0 = time.time()
        resp = ""
        while time.time() - t0 < 2.0 and not resp.startswith(("OK ORDEN", "ERROR ORDEN")):
            resp = leer()
        if resp:
            break
    print(resp or "sin respuesta despues de 3 intentos")
    if not resp.startswith("OK"):
        return
    while True:                                          # telemetria hasta terminar
        l = leer()
        if l and not l.startswith("EVT LATIDO"):          # el latido llega cada 1 s
            print(l)
        if "a=ESPERANDO_ORDEN" in l or l.startswith("EVT ERROR"):
            return


if __name__ == "__main__":
    main()
