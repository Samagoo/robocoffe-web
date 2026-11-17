"""Phase 5.1b: scale ingestion (bridge -> backend -> database). No UI, no decisions."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import ScaleReading

# A removal and a placement, exactly as the real adapter sent them on 17 Nov
REAL = ["PESO:349.3", "PESO:327.2", "PESO:-40.2", "PESO:0.0", "PESO:3.2", "PESO:231.1", "PESO:349.3"]


def _now(offset_s=0.0):
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_s)).isoformat()


def _batch(lines, source="COM5", start=-10.0, step=0.6):
    return {"source": source, "readings": [
        {"raw": l, "grams": float(l.split(":")[1]), "received_at": _now(start + i * step)}
        for i, l in enumerate(lines)]}


def test_readings_are_stored_exactly_as_received(client, db):
    body = _batch(REAL)
    r = client.post("/api/scale/readings", json=body)
    assert r.status_code == 200 and r.json() == {"stored": len(REAL)}
    rows = db.scalars(select(ScaleReading).order_by(ScaleReading.received_at)).all()
    assert [x.raw for x in rows] == REAL
    assert [x.grams for x in rows] == [349.3, 327.2, -40.2, 0.0, 3.2, 231.1, 349.3]   # undershoot kept
    assert {x.source for x in rows} == {"COM5"}
    # the bridge's reception time is what's stored, in UTC; the backend adds its own ingest time
    assert [x.received_at for x in rows] == [datetime.fromisoformat(x["received_at"]) for x in body["readings"]]
    assert all(x.received_at.utcoffset() == timedelta(0) and x.ingested_at >= x.received_at for x in rows)
    assert all(x.order_id is None for x in rows)                                       # no decisions yet


def test_local_time_offsets_are_normalised_to_utc(client, db):
    local = datetime.now(timezone(timedelta(hours=-6))) - timedelta(seconds=5)
    client.post("/api/scale/readings", json={"source": "COM5", "readings": [
        {"raw": "PESO:0.0", "grams": 0.0, "received_at": local.isoformat()}]})
    row = db.scalar(select(ScaleReading))
    assert row.received_at == local and row.received_at.utcoffset() == timedelta(0)


def test_only_peso_lines_are_accepted(client, db):
    bad = {"source": "COM5", "readings": [{"raw": "EVENTO:TAZA_RETIRADA", "grams": 0.0, "received_at": _now()}]}
    assert client.post("/api/scale/readings", json=bad).status_code == 422
    assert db.scalar(select(ScaleReading)) is None


def test_invalid_readings_rejected(client):
    cases = [
        {"raw": "PESO:1", "grams": 1.0, "received_at": "2026-11-17T10:00:00"},     # no UTC offset
        {"raw": "PESO:1", "grams": 1.0, "received_at": _now(3600)},                  # in the future
        {"raw": "PESO:x", "grams": "NaN", "received_at": _now()},                     # not a number
    ]
    for reading in cases:
        assert client.post("/api/scale/readings", json={"source": "COM5", "readings": [reading]}).status_code == 422
    assert client.post("/api/scale/readings", json={"source": "", "readings": []}).status_code == 422


def test_empty_batch_is_fine(client):
    assert client.post("/api/scale/readings", json={"source": "COM5", "readings": []}).json() == {"stored": 0}


def test_read_back_oldest_first_and_by_source(client):
    client.post("/api/scale/readings", json=_batch(["PESO:1.0", "PESO:2.0", "PESO:3.0"], start=-5))
    client.post("/api/scale/readings", json=_batch(["PESO:9.0"], source="COM9", start=-1))
    data = client.get("/api/scale/readings", params={"seconds": 60, "source": "COM5"}).json()
    assert [d["grams"] for d in data] == [1.0, 2.0, 3.0]
    s = {x["source"]: x for x in client.get("/api/scale/summary").json()}
    assert s["COM5"]["count"] == 3 and s["COM5"]["min_grams"] == 1.0 and s["COM9"]["count"] == 1
