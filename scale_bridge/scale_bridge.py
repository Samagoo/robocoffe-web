"""RoboCoffee scale bridge, step 5.1b: HC-05 COM port -> timestamped readings -> backend database.

Reads the lines the deployed adapter firmware sends. The ONLY supported payload is
    PESO:<g>        e.g.  PESO:349.2   PESO:0.0   PESO:-40.2
Every other line (e.g. EVENTO:TAZA_RETIRADA from an old firmware experiment) is ignored entirely:
not printed, not forwarded, not stored. The weight stream is the only source of truth.

Each reading is stamped with THIS PC's time the moment it is read (the adapter has no clock),
printed, and forwarded to the backend (POST /api/scale/readings), which stores it. No decisions here.

    py scale_bridge.py --list                    # show COM ports
    py scale_bridge.py --port COM5               # read + print + forward to http://localhost:8000
    py scale_bridge.py --port COM5 --quiet       # status line every 30 s instead of every reading
    py scale_bridge.py --port COM5 --no-backend  # console only (step 5.1a behaviour)

If the backend is down or doesn't have the endpoint yet, readings wait in memory (up to ~3 h) and are
sent later, in order. Needs Python 3.10+ and `py -m pip install pyserial`.
"""
import argparse
import json
import math
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone

VERSION = "5.1b"
LINE_RE = re.compile(r"^PESO:\s*(-?\d+(?:\.\d+)?)\s*$")
GAP_WARN_S = 1.5            # flag a reading that arrives this long after the previous one
MAX_QUEUE = 20_000          # readings kept while the backend is unreachable (~3 h at 0.6 s)
BATCH = 200
STATUS_EVERY_S = 30.0
RETRYABLE_HTTP = {404, 408, 429}   # 404: backend running but endpoint not deployed yet -> keep data


def parse_line(raw: str) -> float | None:
    """'PESO:349.3' -> 349.3. Anything else -> None (ignored)."""
    m = LINE_RE.match(raw.strip())
    if not m:
        return None
    g = float(m.group(1))
    return g if math.isfinite(g) else None


def now_local() -> datetime:
    """This PC's time with its UTC offset."""
    return datetime.now().astimezone()


def fmt(t: datetime) -> str:
    z = t.strftime("%z")
    return t.strftime("%Y-%m-%d %H:%M:%S.") + f"{t.microsecond // 1000:03d} {z[:3]}:{z[3:]}"


def http_post(url: str, payload: dict, timeout: float = 3.0) -> None:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout):
        pass


# ====================================================================== forwarding
class Forwarder:
    """Sends readings to the backend in order, in batches, from a background thread.
    Network errors, 5xx and 404/408/429 -> keep and retry. Other 4xx -> the backend refuses the
    data itself: drop that batch loudly (retrying would block every reading behind it)."""

    def __init__(self, backend: str, source: str, post=http_post, log=print):
        self.url = backend.rstrip("/") + "/api/scale/readings"
        self.source, self.post, self.log = source, post, log
        self.q: deque[dict] = deque()
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stopped = threading.Event()
        self.sent = self.rejected = self.dropped = self.errors = 0
        self._ok: bool | None = None

    def add(self, reading: dict) -> None:
        with self.lock:
            if len(self.q) >= MAX_QUEUE:
                self.q.popleft()
                self.dropped += 1
            self.q.append(reading)
        self.wake.set()

    @property
    def queued(self) -> int:
        return len(self.q)

    def _state(self, ok: bool, why: str = "") -> None:
        if ok != self._ok:
            self._ok = ok
            self.log(f"[bridge] backend {self.url}: " + ("OK, storing readings" if ok else
                     f"NOT STORING ({why}); readings are kept and will be sent later"))

    def flush_once(self) -> bool:
        """Send one batch. Returns True if the queue moved (sent or rejected)."""
        with self.lock:
            batch = [self.q.popleft() for _ in range(min(BATCH, len(self.q)))]
        if not batch:
            return False
        try:
            self.post(self.url, {"source": self.source, "readings": batch})
        except urllib.error.HTTPError as ex:
            if 400 <= ex.code < 500 and ex.code not in RETRYABLE_HTTP:
                body = ex.read().decode(errors="replace")[:300] if ex.fp else ""
                self.rejected += len(batch)
                self.log(f"[bridge] backend REJECTED {len(batch)} readings (HTTP {ex.code}): {body}")
                return True
            self._requeue(batch)
            self._state(False, f"HTTP {ex.code}")
            return False
        except Exception as ex:                     # connection refused, timeout, DNS...
            self._requeue(batch)
            self._state(False, str(getattr(ex, "reason", ex)))
            return False
        self.sent += len(batch)
        self._state(True)
        return True

    def _requeue(self, batch: list[dict]) -> None:
        with self.lock:
            self.q.extendleft(reversed(batch))
            while len(self.q) > MAX_QUEUE:
                self.q.popleft()
                self.dropped += 1
            self.errors += 1

    def run(self) -> None:
        backoff = 0.5
        while not self.stopped.is_set():
            self.wake.wait(0.5)
            self.wake.clear()
            while self.q and not self.stopped.is_set():
                if self.flush_once():
                    backoff = 0.5
                else:
                    self.stopped.wait(backoff)
                    backoff = min(backoff * 2, 5.0)
                    break

    def start(self) -> None:
        threading.Thread(target=self.run, daemon=True, name="forwarder").start()

    def drain(self, timeout: float) -> None:
        end = time.monotonic() + timeout
        while self.q and time.monotonic() < end:
            self.wake.set()
            time.sleep(0.1)
        self.stopped.set()


# ====================================================================== reading
class Stats:
    def __init__(self):
        self.valid = self.ignored = 0
        self.first = self.last = None
        self.max_gap = 0.0
        self.min_g = self.max_g = None

    def add(self, t: datetime, grams: float) -> float | None:
        dt = (t - self.last).total_seconds() if self.last else None
        if dt is not None:
            self.max_gap = max(self.max_gap, dt)
        self.first, self.last = self.first or t, t
        self.valid += 1
        self.min_g = grams if self.min_g is None else min(self.min_g, grams)
        self.max_g = grams if self.max_g is None else max(self.max_g, grams)
        return dt

    def summary(self) -> str:
        if not self.valid:
            return f"no PESO readings ({self.ignored} other lines ignored)"
        n = self.valid
        period = (self.last - self.first).total_seconds() / (n - 1) if n > 1 else float("nan")
        return (f"{n} readings · mean period {period:.3f} s · largest gap {self.max_gap:.3f} s · "
                f"range {self.min_g:.1f} to {self.max_g:.1f} g · {self.ignored} non-PESO lines ignored")


class Bridge:
    def __init__(self, source: str, forwarder: Forwarder | None, quiet: bool = False, out=sys.stdout):
        self.source, self.fwd, self.quiet, self.out = source, forwarder, quiet, out
        self.stats = Stats()

    def handle_line(self, raw: str) -> None:
        t = now_local()                                   # stamp first, closest to reception
        grams = parse_line(raw)
        if grams is None:
            if raw.strip():
                self.stats.ignored += 1                   # not PESO: ignored entirely
            return
        dt = self.stats.add(t, grams)
        if self.fwd:
            self.fwd.add({"raw": raw.strip(), "grams": grams,
                          "received_at": t.astimezone(timezone.utc).isoformat()})
        if not self.quiet:
            dt_txt = "" if dt is None else f"   dt={dt:.3f} s" + ("   <-- gap" if dt > GAP_WARN_S else "")
            print(f"{fmt(t)}   {grams:7.1f} g{dt_txt}", file=self.out, flush=True)

    def status_line(self) -> str:
        s, f = self.stats, self.fwd
        last = f"{s.last and fmt(s.last)}" if s.last else "never"
        fw = f" · stored {f.sent} · waiting {f.queued}" + (f" · rejected {f.rejected}" if f.rejected else "") \
            + (f" · dropped {f.dropped}" if f.dropped else "") if f else ""
        return f"[bridge] {self.source} · readings {s.valid}{fw} · last {last}"


def run(port: str, baud: int, bridge: Bridge) -> None:
    import serial  # pyserial

    last_status = time.monotonic()
    while True:
        try:
            ser = serial.serial_for_url(port, baud, timeout=1)    # "COM5", or a pseudo-terminal in tests
        except (serial.SerialException, OSError) as ex:
            print(f"[bridge] cannot open {port}: {ex}  (retrying in 3 s)", flush=True)
            time.sleep(3)
            continue
        print(f"[bridge] {port} open at {baud} baud. Waiting for PESO: lines...  (Ctrl+C to stop)", flush=True)
        buf, silent_since, warned = b"", time.monotonic(), False
        try:
            while True:
                data = ser.read(ser.in_waiting or 1)
                now = time.monotonic()
                if now - last_status >= STATUS_EVERY_S and bridge.fwd:
                    print(bridge.status_line(), flush=True)
                    last_status = now
                if not data:                                    # 1 s read timeout: silence is not a reading
                    if not warned and now - silent_since > 3:
                        print("[bridge] no data for 3 s (adapter off, out of range, or not paired?)", flush=True)
                        warned = True
                    continue
                silent_since, warned = now, False
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    bridge.handle_line(line.decode("ascii", errors="replace"))
                if len(buf) > 200:                              # garbage without a newline
                    buf = b""
        except (serial.SerialException, OSError) as ex:
            print(f"[bridge] {port} lost: {ex}  (reconnecting in 2 s)", flush=True)
        finally:
            try:
                ser.close()
            except Exception:
                pass
        time.sleep(2)


def list_ports() -> None:
    from serial.tools import list_ports as lp

    ports = list(lp.comports())
    if not ports:
        print("no serial ports found")
    for p in ports:
        print(f"{p.device:8} {p.description}  [{p.hwid}]")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--port", help="COM port of the HC-05, e.g. COM5")
    g.add_argument("--list", action="store_true", help="list serial ports and exit")
    ap.add_argument("--baud", type=int, default=9600, help="HC-05 baud rate (default 9600)")
    ap.add_argument("--backend", default="http://localhost:8000", help="backend base URL")
    ap.add_argument("--no-backend", action="store_true", help="only print, don't forward")
    ap.add_argument("--quiet", action="store_true", help="don't print every reading")
    a = ap.parse_args(argv)
    if a.list:
        return list_ports()

    fwd = None if a.no_backend else Forwarder(a.backend, a.port)
    bridge = Bridge(a.port, fwd, quiet=a.quiet)
    print(f"[bridge] v{VERSION} port={a.port} " + ("(console only)" if fwd is None else f"backend={a.backend}"),
          flush=True)
    if fwd:
        fwd.start()
    try:
        run(a.port, a.baud, bridge)
    except KeyboardInterrupt:
        print("", flush=True)
    finally:
        if fwd:
            fwd.drain(5.0)
        print(f"[bridge] stopped · {bridge.stats.summary()}", flush=True)
        if fwd:
            lost = f" · {fwd.queued} NOT stored (backend unreachable at exit)" if fwd.queued else ""
            print(f"[bridge] stored {fwd.sent}{lost}", flush=True)


if __name__ == "__main__":
    main()
