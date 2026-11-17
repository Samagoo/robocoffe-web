"""Bridge tests, no hardware and no backend needed:  py -m pytest scale_bridge"""
import io
import urllib.error
from datetime import datetime, timedelta

import pytest

import scale_bridge as sb


# ---------------------------------------------------------------- parsing
@pytest.mark.parametrize("raw, grams", [
    ("PESO:349.2", 349.2), ("PESO:0.0", 0.0), ("PESO:-40.2", -40.2), ("PESO:349.3\r", 349.3), (" PESO: 12 ", 12.0)])
def test_peso_lines_are_parsed(raw, grams):
    assert sb.parse_line(raw) == grams


@pytest.mark.parametrize("raw", ["EVENTO:TAZA_RETIRADA", "LISTO", "PESO:", "PESO:abc", "peso:1.0", "PESO:nan", ""])
def test_everything_else_is_not_a_reading(raw):
    assert sb.parse_line(raw) is None


# ---------------------------------------------------------------- non-PESO lines ignored entirely
class FakeBackend:
    def __init__(self, fail=0, error=None):
        self.fail, self.error, self.batches = fail, error, []

    def __call__(self, url, payload):
        if self.fail > 0:
            self.fail -= 1
            raise self.error or ConnectionRefusedError("refused")
        self.batches.append(payload)

    @property
    def readings(self):
        return [r for b in self.batches for r in b["readings"]]


def test_non_peso_lines_are_not_printed_forwarded_or_stored():
    backend, out = FakeBackend(), io.StringIO()
    fwd = sb.Forwarder("http://x", "COM5", post=backend, log=lambda *_: None)
    b = sb.Bridge("COM5", fwd, out=out)
    for line in ["PESO:349.2", "EVENTO:TAZA_RETIRADA", "PESO:-40.2", "PESO:0.0"]:
        b.handle_line(line)
    fwd.flush_once()
    assert [r["raw"] for r in backend.readings] == ["PESO:349.2", "PESO:-40.2", "PESO:0.0"]
    assert "EVENTO" not in out.getvalue()
    assert b.stats.valid == 3 and b.stats.ignored == 1


def test_readings_carry_pc_utc_time_in_order():
    backend = FakeBackend()
    fwd = sb.Forwarder("http://x", "COM5", post=backend, log=lambda *_: None)
    b = sb.Bridge("COM5", fwd, quiet=True)
    for g in ("0.0", "8.4", "245.8", "349.4"):
        b.handle_line(f"PESO:{g}")
    fwd.flush_once()
    assert backend.batches[0]["source"] == "COM5"
    stamps = [datetime.fromisoformat(r["received_at"]) for r in backend.readings]
    assert all(s.utcoffset() == timedelta(0) for s in stamps) and stamps == sorted(stamps)


# ---------------------------------------------------------------- forwarding resilience
def _filled(n, backend):
    fwd = sb.Forwarder("http://x", "COM5", post=backend, log=lambda *_: None)
    for i in range(n):
        fwd.add({"raw": f"PESO:{i}.0", "grams": float(i), "received_at": "t"})
    return fwd


def _flush_all(fwd, tries=30):
    for _ in range(tries):
        if not fwd.q:
            break
        fwd.flush_once()


def test_backend_down_then_up_nothing_lost_order_kept():
    backend = FakeBackend(fail=3)
    fwd = _filled(450, backend)
    _flush_all(fwd)
    assert [r["grams"] for r in backend.readings] == [float(i) for i in range(450)]
    assert fwd.errors == 3 and fwd.sent == 450


def test_404_endpoint_missing_is_retried_not_dropped():
    """What you saw today: Phase 4 backend without the endpoint -> keep everything."""
    err = urllib.error.HTTPError("http://x", 404, "Not Found", {}, None)
    backend = FakeBackend(fail=2, error=err)
    fwd = _filled(10, backend)
    _flush_all(fwd)
    assert len(backend.readings) == 10 and fwd.rejected == 0


def test_422_rejected_batch_is_dropped_so_it_cannot_block_the_queue():
    err = urllib.error.HTTPError("http://x", 422, "Unprocessable", {}, io.BytesIO(b'{"detail":"bad"}'))
    backend = FakeBackend(fail=1, error=err)
    fwd = _filled(5, backend)
    fwd.add({"raw": "PESO:9.0", "grams": 9.0, "received_at": "t"})
    _flush_all(fwd)
    assert fwd.rejected == 6 and backend.readings == []        # one batch of 6, refused once
    fwd.add({"raw": "PESO:1.0", "grams": 1.0, "received_at": "t"})
    _flush_all(fwd)
    assert [r["grams"] for r in backend.readings] == [1.0]     # later readings still flow


def test_queue_is_bounded_oldest_dropped_first(monkeypatch):
    monkeypatch.setattr(sb, "MAX_QUEUE", 5)
    fwd = _filled(8, FakeBackend(fail=99))
    assert fwd.queued == 5 and fwd.dropped == 3
    assert [r["grams"] for r in fwd.q] == [3.0, 4.0, 5.0, 6.0, 7.0]


# ---------------------------------------------------------------- serial path (POSIX only)
@pytest.mark.skipif(__import__("sys").platform == "win32", reason="uses a pseudo-terminal as a fake COM port")
def test_serial_port_to_forwarder():
    import os
    import threading
    import time
    import tty

    pytest.importorskip("serial")
    master, slave = os.openpty()
    tty.setraw(slave)
    backend = FakeBackend()
    fwd = sb.Forwarder("http://x", "COMX", post=backend, log=lambda *_: None)
    b = sb.Bridge("COMX", fwd, quiet=True)
    threading.Thread(target=sb.run, args=(os.ttyname(slave), 9600, b), daemon=True).start()
    time.sleep(0.5)
    for chunk in [b"PESO:349", b".2\r\nEVENTO:TAZA_RETIRADA\r\nPE", b"SO:-40.2\r\nPESO:0.0\r\n"]:
        os.write(master, chunk)
        time.sleep(0.05)
    for _ in range(40):
        if b.stats.valid == 3:
            break
        time.sleep(0.05)
    fwd.flush_once()
    assert [r["grams"] for r in backend.readings] == [349.2, -40.2, 0.0]
    assert b.stats.ignored == 1
