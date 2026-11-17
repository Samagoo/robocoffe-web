"""Bridge tests (no hardware, no backend):  py -m pytest scale_bridge"""
import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scale_bridge as sb  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "bench_2026-11-17.txt"


@pytest.mark.parametrize("raw, grams", [
    ("PESO:349.3", 349.3), ("PESO:0.0", 0.0), ("PESO:-30.3", -30.3), ("PESO:8.4", 8.4),
    ("PESO:349.3\r", 349.3), ("  PESO: 12 ", 12.0),
])
def test_parse_valid(raw, grams):
    assert sb.parse_line(raw) == grams


@pytest.mark.parametrize("raw", ["", "LISTO", "PESO:", "PESO:abc", "PESO:3.4.5", "PES", "peso:1.0", "PESO:nan"])
def test_parse_invalid(raw):
    assert sb.parse_line(raw) is None


class Recorder:
    """Stands in for the backend. fail_first: fail that many /readings posts first."""
    def __init__(self, fail_first=0):
        self.fail_first, self.readings, self.links = fail_first, [], []

    def __call__(self, url, payload):
        if url.endswith("/link"):
            self.links.append(payload)
            return
        if self.fail_first > 0:
            self.fail_first -= 1
            raise ConnectionError("backend down")
        self.readings.extend(payload["readings"])


def _bridge(tmp_path, post):
    return sb.Bridge("test", "http://x", log_dir=str(tmp_path), post=post)


def test_real_bench_log_goes_through_unchanged_and_in_order(tmp_path):
    rec = Recorder()
    b = _bridge(tmp_path, rec)
    lines = SAMPLE.read_text().splitlines()
    for l in lines:
        b.on_line(l)
    while b.flush_once():
        pass
    assert len(rec.readings) == len(lines) == b.counters["valid"]
    assert [r["raw"] for r in rec.readings] == lines
    assert min(r["grams"] for r in rec.readings) == -50.0          # undershoot frames are kept
    stamps = [datetime.fromisoformat(r["received_at"]) for r in rec.readings]
    assert all(s.utcoffset() == timedelta(0) for s in stamps)
    assert stamps == sorted(stamps)


def test_invalid_lines_are_counted_logged_and_not_sent(tmp_path):
    rec = Recorder()
    b = _bridge(tmp_path, rec)
    for l in ["LISTO", "PESO:1.5", "basura", "PESO:2.0"]:
        b.on_line(l)
    b.flush_once()
    assert [r["grams"] for r in rec.readings] == [1.5, 2.0]
    assert (b.counters["valid"], b.counters["invalid"]) == (2, 2)
    rows = list(csv.reader(open(next(tmp_path.glob("scale_raw_*.csv")), encoding="utf-8")))
    assert rows[0][0] == "received_at_utc" and [r[2] for r in rows[1:]] == ["LISTO", "PESO:1.5", "basura", "PESO:2.0"]


def test_backend_down_nothing_lost_order_kept(tmp_path):
    rec = Recorder(fail_first=3)
    b = _bridge(tmp_path, rec)
    for i in range(450):                                   # > 2 batches
        b.on_line(f"PESO:{i}.0")
    tries = 0
    while b.q and tries < 20:
        b.flush_once()
        tries += 1
    assert [r["grams"] for r in rec.readings] == [float(i) for i in range(450)]
    assert b.counters["post_errors"] == 3 and b.counters["dropped"] == 0


def test_queue_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "MAX_QUEUE", 5)
    b = _bridge(tmp_path, Recorder(fail_first=99))
    for i in range(8):
        b.on_line(f"PESO:{i}.0")
    assert len(b.q) == 5 and b.counters["dropped"] == 3
    assert [r["grams"] for r in b.q] == [3.0, 4.0, 5.0, 6.0, 7.0]  # oldest dropped first


def test_link_changes_are_reported(tmp_path):
    rec = Recorder()
    b = _bridge(tmp_path, rec)
    b.set_link(True)
    b.set_link(True)                       # no change: not re-sent
    b.set_link(False, "lost: device disconnected")
    assert [(l["port_open"], l["detail"]) for l in rec.links] == [(True, ""), (False, "lost: device disconnected")]


def test_sim_adapter_reproduces_real_artifacts(tmp_path):
    rec = Recorder()
    b = _bridge(tmp_path, rec)
    sim = sb.SimAdapter(b, period=0)
    sim.command("poner 349.3")
    sim.command("quitar")
    frames = list(sim.script)
    assert frames[:2] == [10.5, 244.5] and frames[-1] == -40.2   # intermediate + undershoot


def test_replay_reads_our_own_csv(tmp_path):
    b = _bridge(tmp_path, Recorder())
    for l in ["PESO:1.0", "PESO:2.0"]:
        b.on_line(l)
    csv_path = next(tmp_path.glob("scale_raw_*.csv"))
    assert sb._read_log(str(csv_path)) == ["PESO:1.0", "PESO:2.0"]


@pytest.mark.skipif(sys.platform == "win32", reason="uses a POSIX pseudo-terminal as a fake COM port")
def test_serial_reader_reassembles_split_lines(tmp_path):
    """Feeds a pseudo-terminal like the HC-05 would: CRLF endings, lines split across reads."""
    import os
    import threading
    import time

    pytest.importorskip("serial")
    master, slave = os.openpty()
    rec = Recorder()
    b = _bridge(tmp_path, rec)
    threading.Thread(target=sb.run_serial, args=(b, os.ttyname(slave), 9600), daemon=True).start()
    for _ in range(50):
        if b.port_open:
            break
        time.sleep(0.05)
    for chunk in [b"PESO:349", b".3\r\nPESO:0.0\r\nPE", b"SO:-40.2\r\n"]:
        os.write(master, chunk)
        time.sleep(0.05)
    for _ in range(50):
        if b.counters["valid"] == 3:
            break
        time.sleep(0.05)
    b.flush_once()
    assert [r["grams"] for r in rec.readings] == [349.3, 0.0, -40.2]
    assert rec.links[0]["port_open"] is True
