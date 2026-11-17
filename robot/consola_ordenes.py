"""Consola de ordenes: escribes MESA1, MESA2, MESA3, PAUSA... y ves en vivo lo que hace el robot.

Funciona igual con la simulacion de Webots (oak9_entregas.wbt) y con el robot real (main_real.py):
los dos escuchan ordenes por TCP en el puerto 9000.

    python consola_ordenes.py                    # misma computadora (127.0.0.1:9000)
    python consola_ordenes.py --host 192.168.1.20

Comandos:  MESA1  MESA2  MESA3   RETIRADO (el cliente tomo el vaso)
           PAUSA  REANUDAR  CANCELAR  RESET  ESTADO  SALIR
"""
import argparse
import socket
import threading
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--puerto", type=int, default=9000)
    a = ap.parse_args()
    try:
        s = socket.create_connection((a.host, a.puerto), timeout=3)
    except OSError:
        print(f"No me pude conectar a {a.host}:{a.puerto}. Revisa que la simulacion este corriendo "
              "(boton Play, no en pausa) o que main_real.py este abierto.")
        return
    s.settimeout(None)
    estado = {"orden": None, "ultimo_id": 0}

    def nuevo_id():
        estado["ultimo_id"] = max(estado["ultimo_id"] + 1, int(time.time() * 10))
        return estado["ultimo_id"]

    def escuchar():
        buf = ""
        while True:
            try:
                d = s.recv(4096)
            except OSError:
                break
            if not d:
                break
            buf += d.decode(errors="replace")
            while "\n" in buf:
                linea, _, buf = buf.partition("\n")
                linea = linea.strip()
                if not linea or linea.startswith("EVT LATIDO"):
                    continue
                if linea.startswith("OK ORDEN"):
                    estado["orden"] = linea.split("id=")[1].split()[0]
                print(f"\r  {linea}\noak9> ", end="", flush=True)
        print("\nSe cerro la conexion con el robot.")

    threading.Thread(target=escuchar, daemon=True).start()
    print(f"Conectado a {a.host}:{a.puerto}.")
    print("Comandos: MESA1 MESA2 MESA3  RETIRADO  PAUSA REANUDAR CANCELAR RESET ESTADO  SALIR")
    while True:
        try:
            cmd = input("oak9> ").strip().upper().replace(" ", "")
        except (EOFError, KeyboardInterrupt):
            break
        if not cmd:
            continue
        if cmd == "SALIR":
            break
        if cmd in ("MESA1", "MESA2", "MESA3"):
            linea = f"ORDEN id={nuevo_id()} destino={cmd}"
        elif cmd == "CANCELAR":
            linea = f"CANCELAR id={nuevo_id()} orden={estado['orden']}"
        elif cmd in ("PAUSA", "REANUDAR", "RESET", "ESTADO", "PING", "RETIRADO"):
            linea = f"{cmd} id={nuevo_id()}"
        else:
            print("No entendi. Comandos: MESA1 MESA2 MESA3  RETIRADO  PAUSA REANUDAR CANCELAR RESET ESTADO  SALIR")
            continue
        s.sendall((linea + "\n").encode())
    s.close()


if __name__ == "__main__":
    main()
