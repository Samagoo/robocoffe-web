import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Order, OrderEvent
from app.order_config import get_order_config


def _order(client, **kw):
    body = {"product_code": "C1", "table_number": 2} | kw
    return client.post("/api/orders", json=body)


# ---------------------------------------------------------------- health (Phase 1 still works)
def test_health_reports_db_and_schema_revision(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["database"]["schema_revision"] == _alembic_head()


def _alembic_head() -> str:
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


# ---------------------------------------------------------------- POST /api/orders
def test_create_order_persists_with_initial_status(client, db):
    r = _order(client, customer_name="  Ana ", notes="sin azúcar")
    assert r.status_code == 201, r.text
    o = r.json()
    cfg = get_order_config()
    assert re.fullmatch(r"P-\d{4,}", o["folio"])
    assert o["status"] == cfg.initial_status
    assert o["product_code"] == "C1"
    assert o["table_number"] == 2
    assert o["distance_m"] == cfg.table(2).distance_m
    assert o["customer_name"] == "Ana"
    assert o["dispatched_at"] is None and o["robot_msg_id"] is None

    row = db.get(Order, o["id"])
    assert row is not None and row.folio == o["folio"]


def test_create_order_writes_creation_event_with_same_timestamp(client, db):
    o = _order(client).json()
    events = db.scalars(select(OrderEvent).where(OrderEvent.order_id == o["id"])).all()
    assert len(events) == 1
    ev = events[0]
    assert (ev.from_status, ev.to_status, ev.source) == (None, o["status"], "customer")
    assert ev.created_at.isoformat() == datetime.fromisoformat(o["created_at"]).isoformat()


def test_timestamps_are_utc_and_current(client):
    o = _order(client).json()
    created = datetime.fromisoformat(o["created_at"])
    assert created.utcoffset() == timedelta(0)
    assert abs(datetime.now(timezone.utc) - created) < timedelta(seconds=30)


def test_product_code_is_normalised(client):
    assert _order(client, product_code=" c3 ").json()["product_code"] == "C3"


def test_blank_customer_name_becomes_null(client):
    assert _order(client, customer_name="   ").json()["customer_name"] is None


def test_unknown_table_rejected(client):
    r = _order(client, table_number=4)
    assert r.status_code == 422 and "unknown table" in r.text


def test_unknown_product_rejected(client):
    r = _order(client, product_code="C9")
    assert r.status_code == 422 and "unknown product" in r.text


def test_missing_fields_rejected(client):
    assert client.post("/api/orders", json={"table_number": 1}).status_code == 422
    assert client.post("/api/orders", json={"product_code": "C1"}).status_code == 422


def test_folios_are_sequential(client):
    a = int(_order(client).json()["folio"][2:])
    b = int(_order(client).json()["folio"][2:])
    assert b == a + 1


# ---------------------------------------------------------------- GET /api/orders
def test_list_newest_first(client):
    first = _order(client).json()["id"]
    second = _order(client).json()["id"]
    ids = [o["id"] for o in client.get("/api/orders").json()]
    assert ids.index(second) < ids.index(first)


def test_list_filter_by_status(client):
    _order(client)
    initial = get_order_config().initial_status
    data = client.get("/api/orders", params={"status": initial}).json()
    assert data and all(o["status"] == initial for o in data)


def test_list_unknown_status_rejected(client):
    assert client.get("/api/orders", params={"status": "NOPE"}).status_code == 422


def test_list_limit(client):
    for _ in range(3):
        _order(client)
    assert len(client.get("/api/orders", params={"limit": 2}).json()) == 2
    assert client.get("/api/orders", params={"limit": 0}).status_code == 422


# ---------------------------------------------------------------- GET /api/catalog
def test_catalog(client):
    data = client.get("/api/catalog").json()
    assert [t["number"] for t in data["tables"]] == [1, 2, 3]
    assert data["initial_status"] in data["statuses"]
