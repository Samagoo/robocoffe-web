"""Canales de ordenes intercambiables (seccion 7.3). Todos mandan y reciben lineas.

CanalTCP     CANAL PRINCIPAL: servidor TCP por WiFi (puerto 9000); la plataforma es el cliente.
             Acepta varios clientes; respuestas y eventos van a todos.
             TCP no respeta limites de mensaje: _Lineas arma lineas completas por '\n'.
CanalConsola teclea las ordenes en la terminal (pruebas)
CanalMemoria pruebas automaticas
CanalSerie   puerto serie; sin uso en este diseno (el firmware del OAK9 no permite Bluetooth)
"""
import queue
import socket
import sys
import threading


class CanalMemoria:
    def __init__(self):
        self.entrada, self.salida = [], []

    def leer(self):
        out, self.entrada = self.entrada, []
        return out

    def enviar(self, linea):
        self.salida.append(linea)


class _Lineas:
    """Arma lineas completas; descarta un fragmento sin '\\n' despues de 1 s."""
    def __init__(self):
        self.buf, self.t = "", None

    def agregar(self, texto, t):
        if texto and not self.buf:
            self.t = t
        self.buf += texto
        lineas = []
        while "\n" in self.buf:
            l, _, self.buf = self.buf.partition("\n")
            if l.strip():
                lineas.append(l.strip())
        if self.buf and self.t is not None and t - self.t > 1.0:
            self.buf = ""
        return lineas


class CanalSerie:
    def __init__(self, puerto, baud=9600):
        import serial                                   # pip install pyserial
        import time
        self._time = time
        self.s = serial.Serial(puerto, baud, timeout=0)
        self.lin = _Lineas()

    def leer(self):
        data = self.s.read(self.s.in_waiting or 1).decode("utf-8", errors="replace")
        return self.lin.agregar(data, self._time.monotonic())

    def enviar(self, linea):
        try:
            self.s.write((linea + "\n").encode("utf-8"))
        except Exception:
            pass          # perder el canal de ordenes NO cambia el estado (seccion 6.2)


class CanalTCP:
    """Servidor TCP en el puerto 9000. Acepta VARIOS clientes a la vez (la plataforma web y, para
    depurar, consola_ordenes.py). Lo que sale (respuestas OK/ERROR y eventos EVT) va a TODOS los
    clientes conectados. Si un cliente se desconecta el robot sigue igual (seccion 6.2)."""
    def __init__(self, puerto=9000, max_clientes=4):
        import time
        self._time = time
        self.max_clientes = max_clientes
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("0.0.0.0", puerto))
        self.srv.listen(max_clientes)
        self.srv.setblocking(False)
        self.clientes = {}                      # socket -> _Lineas (cada uno arma sus lineas)

    def _aceptar(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except (BlockingIOError, OSError):
                return
            if len(self.clientes) >= self.max_clientes:
                c.close()
                continue
            c.setblocking(False)
            self.clientes[c] = _Lineas()

    def _cerrar(self, c):
        self.clientes.pop(c, None)
        try:
            c.close()
        except OSError:
            pass

    def leer(self):
        self._aceptar()
        lineas = []
        for c, lin in list(self.clientes.items()):
            try:
                data = c.recv(4096)
            except BlockingIOError:
                continue
            except OSError:
                self._cerrar(c)
                continue
            if not data:
                self._cerrar(c)
                continue
            lineas += lin.agregar(data.decode("utf-8", errors="replace"), self._time.monotonic())
        return lineas

    def enviar(self, linea):
        dato = (linea + "\n").encode("utf-8")
        for c in list(self.clientes):
            try:
                c.sendall(dato)
            except OSError:                     # incluye un cliente que no lee (buffer lleno)
                self._cerrar(c)


class CanalConsola:
    def __init__(self):
        self.q = queue.Queue()
        threading.Thread(target=self._leer, daemon=True).start()

    def _leer(self):
        for linea in sys.stdin:
            self.q.put(linea.strip())

    def leer(self):
        out = []
        while not self.q.empty():
            out.append(self.q.get())
        return out

    def enviar(self, linea):
        pass              # el Ejecutor ya imprime todo
