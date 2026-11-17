"""A scripted stand-in for main_real.py, for tests only.

It is a SERVER that speaks the robot's line protocol (OK/ERROR/EVT on port 9000), so the
platform's real ClienteRobot can be exercised without the simulator. Modes for ORDEN:
  accept      OK ORDEN + EVT TRANSICION (normal case)
  reject      ERROR ORDEN <reason>
  silent      ignores ORDEN completely (robot never got it)
  reply_lost  starts the trip and sends EVT TRANSICION, but never the OK reply
"""
import asyncio
import threading


class FakeRobot:
    def __init__(self):
        self.mode = "accept"
        self.reject_reason = "OCUPADO"
        self.state = "ESPERANDO_ORDEN"
        self.order = "-"
        self.received: list[str] = []
        self.port = None
        self._writers: set[asyncio.StreamWriter] = set()
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()

    # ------------------------------------------------------------ lifecycle
    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(5)
        return self

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._server = self._loop.run_until_complete(asyncio.start_server(self._handle, "127.0.0.1", 0))
        self.port = self._server.sockets[0].getsockname()[1]
        self._ready.set()
        self._loop.run_forever()

    def stop(self):
        if not self._loop.is_running():          # already stopped (idempotent)
            return

        async def _close():
            self._server.close()
            for w in list(self._writers):
                w.close()
        asyncio.run_coroutine_threadsafe(_close(), self._loop).result(5)
        self._loop.call_soon_threadsafe(self._loop.stop)

    def emit(self, line: str):
        """Send a line (e.g. an EVT) to every connected client, from the test thread."""
        self._loop.call_soon_threadsafe(self._send, line)

    # ------------------------------------------------------------ protocol
    def _send(self, line: str):
        for w in list(self._writers):
            w.write((line + "\n").encode())

    async def _handle(self, reader, writer):
        self._writers.add(writer)
        try:
            while line := await reader.readline():
                self._process(line.decode().strip())
        finally:
            self._writers.discard(writer)

    def _process(self, line: str):
        self.received.append(line)
        parts = line.split()
        cmd = parts[0]
        f = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
        mid = f.get("id")
        if cmd == "ESTADO":
            self._send(f"OK ESTADO id={mid} estado={self.state} orden={self.order} tramo=- "
                       f"x=0.000 y=0.000 th=0.0 error=-")
        elif cmd == "ORDEN":
            if self.mode == "silent":
                return
            if self.mode == "reject":
                self._send(f"ERROR ORDEN id={mid} {self.reject_reason}")
                return
            if self.order == mid:                 # retry with the same id: answer, don't start again
                if self.mode == "accept":
                    self._send(f"OK ORDEN id={mid} estado={self.state}")
                return
            mesa = f["destino"][-1]
            self.state, self.order = f"RECORRIDO_MESA_{mesa}", mid
            if self.mode == "accept":
                self._send(f"OK ORDEN id={mid} estado={self.state}")
            self._send(f"EVT TRANSICION t=10.00 de=ESPERANDO_ORDEN a={self.state} causa=orden_MESA{mesa} "
                       f"orden={mid} x=0.000 y=0.000 th=0.0")
