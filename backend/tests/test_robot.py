"""Phase 4: dispatch and robot events through the robot team's real ClienteRobot,
against a scripted fake robot (tests/fake_robot.py). Skipped if robocoffe_cliente.py
isn't available (it's mounted from robot/cliente in Docker)."""
import os
import time

import pytest
from sqlalchemy import select, text

from app.config import settings
from app.models import Order, OrderEvent, RobotEvent
from app.robot.link import load_cliente_robot

from .fake_robot import FakeRobot

CLIENT_DIR = os.environ.get("ROBOT_CLIENT_DIR", settings.robot_client_dir)
pytestmark = pytest.mark.skipif(load_cliente_robot(CLIENT_DIR) is None,
                                reason=f"robocoffe_cliente.py not found in {CLIENT_DIR}")


def _wait(cond, timeout=3.0, msg="condition"):
    end = time.time() + timeout
    while time.time() < end:
        if v := cond():
            return v
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {msg}")


@pytest.fixture
def robot(migrated_database):
    """(TestClient, FakeRobot, Session factory) with a live ClienteRobot connected to the fake."""
    from fastapi.testclient import TestClient

    from app.db import SessionLocal, engine
    from app.main import app

    with engine.begin() as conn:     # these tests commit for real (several sessions/threads)
        conn.execute(text("TRUNCATE orders, order_events, robot_events, scale_readings RESTART IDENTITY CASCADE"))
    fake = FakeRobot().start()
    saved = settings.model_dump()
    settings.robot_enabled, settings.robot_host, settings.robot_port = True, "127.0.0.1", fake.port
    settings.robot_client_dir, settings.robot_poll_s = CLIENT_DIR, 0
    app.dependency_overrides.clear()
    try:
        with TestClient(app) as c:
            link = app.state.robot_link
            _wait(lambda: link.status()["state"] == "ESPERANDO_ORDEN", 5, "robot connected")
            link.client.espera_respuesta = 0.3        # faster "no answer" cases
            yield c, fake, SessionLocal
    finally:
        for k, v in saved.items():
            setattr(settings, k, v)
        fake.stop()
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE orders, order_events, robot_events, scale_readings RESTART IDENTITY CASCADE"))


def _new_order(c, table=2):
    r = c.post("/api/orders", json={"product_code": "C1", "table_number": table})
    assert r.status_code == 201
    return r.json()


def _events(S, order_id):
    with S() as db:
        return [(e.from_status, e.to_status, e.cause, e.source) for e in
                db.scalars(select(OrderEvent).where(OrderEvent.order_id == order_id).order_by(OrderEvent.id))]


# ---------------------------------------------------------------- status
def test_robot_status_exposed(robot):
    c, fake, _ = robot
    fake.emit("EVT LATIDO t=5.00 estado=ESPERANDO_ORDEN bat=7.84")
    s = _wait(lambda: (s := c.get("/api/robot").json())["battery_v"] == 7.84 and s, msg="battery")
    assert s["link"] == "connected" and s["state"] == "ESPERANDO_ORDEN" and s["free"] is True
    assert s["pose"] == {"x": 0.0, "y": 0.0, "th": 0.0}
    assert s["robot_order"] is None and s["last_message_at"].endswith("+00:00")
    assert c.get("/api/health").json()["robot"]["link"] == "connected"


# ---------------------------------------------------------------- dispatch
def test_dispatch_accepted_sends_orden_and_persists(robot):
    c, fake, S = robot
    o = _new_order(c, table=2)
    r = c.post(f"/api/orders/{o['id']}/dispatch")
    assert r.status_code == 200, r.text
    body = r.json()
    mid = body["robot_msg_id"]
    assert body["ok"] and body["robot_state"] == "RECORRIDO_MESA_2"
    assert f"ORDEN id={mid} destino=MESA2" in fake.received          # ClienteRobot.ordenar() format

    order = body["order"]
    assert order["robot_msg_id"] == mid and order["dispatched_at"] is not None
    assert order["status"] == "DESPACHADA"
    assert _events(S, o["id"])[-1][:2] == ("PENDIENTE", "DESPACHADA")

    # the robot's TRANSICION is stored and linked to the order
    ev = _wait(lambda: _robot_event(S, "TRANSICION", mid), msg="TRANSICION stored")
    assert ev.order_id == o["id"] and ev.fields["a"] == "RECORRIDO_MESA_2" and ev.robot_t == 10.0
    assert c.get("/api/robot").json()["robot_order"] == mid


def _robot_event(S, kind, mid):
    with S() as db:
        return db.scalar(select(RobotEvent).where(RobotEvent.event_type == kind, RobotEvent.robot_msg_id == mid))


def test_dispatch_rejected_by_robot_keeps_order_pending(robot):
    c, fake, S = robot
    fake.mode, fake.reject_reason = "reject", "FUERA_DE_BASE"
    o = _new_order(c)
    r = c.post(f"/api/orders/{o['id']}/dispatch")
    assert r.status_code == 409 and r.json()["reason"] == "FUERA_DE_BASE"
    order = r.json()["order"]
    assert order["status"] == "PENDIENTE" and order["robot_msg_id"] is None and order["dispatched_at"] is None
    assert _events(S, o["id"])[-1] == ("PENDIENTE", "PENDIENTE", "dispatch_rejected:FUERA_DE_BASE", "admin")


def test_lost_reply_is_confirmed_by_the_robot(robot):
    c, fake, _ = robot
    fake.mode = "reply_lost"                       # robot starts the trip, OK never arrives
    o = _new_order(c, table=3)
    r = c.post(f"/api/orders/{o['id']}/dispatch")
    assert r.status_code == 200, r.text
    assert r.json()["order"]["status"] == "DESPACHADA" and r.json()["order"]["dispatched_at"]
    mid = r.json()["robot_msg_id"]
    assert sum(1 for l in fake.received if l.startswith(f"ORDEN id={mid}")) >= 2   # retried with SAME id


def test_no_answer_returns_504_and_can_be_retried(robot):
    c, fake, S = robot
    fake.mode = "silent"
    o = _new_order(c)
    r = c.post(f"/api/orders/{o['id']}/dispatch")
    assert r.status_code == 504 and r.json()["reason"] == "SIN_RESPUESTA"
    first = r.json()["robot_msg_id"]
    assert r.json()["order"]["status"] == "PENDIENTE" and r.json()["order"]["robot_msg_id"] == first

    fake.mode = "accept"
    r2 = c.post(f"/api/orders/{o['id']}/dispatch")
    assert r2.status_code == 200 and r2.json()["robot_msg_id"] > first
    causes = [e[2] for e in _events(S, o["id"])]
    # OK reply and the robot's TRANSICION arrive together; whichever is processed first confirms
    assert "dispatch_no_reply" in causes
    assert causes[-1].startswith("robot_ok") or causes[-1] == "confirmed_by_robot_event"
    assert causes.count("dispatch_no_reply") == 1 and len(causes) == 3     # confirmed exactly once
    assert r2.json()["order"]["dispatched_at"] is not None


def test_cannot_dispatch_twice_or_missing(robot):
    c, _, _ = robot
    o = _new_order(c)
    assert c.post(f"/api/orders/{o['id']}/dispatch").status_code == 200
    r = c.post(f"/api/orders/{o['id']}/dispatch")
    assert r.status_code == 409 and "already dispatched" in r.json()["detail"]
    assert c.post("/api/orders/999999/dispatch").status_code == 404


def test_robot_disconnected_gives_503_and_is_recorded(robot):
    c, fake, S = robot
    o = _new_order(c)
    fake.stop()
    _wait(lambda: c.get("/api/robot").json()["link"] == "disconnected", 5, "disconnect")
    r = c.post(f"/api/orders/{o['id']}/dispatch")
    assert r.status_code == 503 and "not connected" in r.json()["detail"]
    with S() as db:
        kinds = [(e.event_type, e.fields) for e in db.scalars(select(RobotEvent).order_by(RobotEvent.id))]
    assert ("CONEXION", {"conectado": True}) in kinds and kinds[-1] == ("CONEXION", {"conectado": False})


# ---------------------------------------------------------------- events + WebSocket
def test_every_evt_is_stored_with_utc_receive_time(robot):
    c, fake, S = robot
    fake.emit("EVT LLEGO t=33.10 mesa=1 orden=-")
    fake.emit("EVT ERROR t=40.00 codigo=E_ATASCO orden=- tramo=1/1")
    ev = _wait(lambda: _robot_event_any(S, "ERROR"), msg="ERROR stored")
    assert ev.fields["codigo"] == "E_ATASCO" and ev.robot_msg_id is None and ev.order_id is None
    assert ev.received_at.utcoffset().total_seconds() == 0
    assert ev.raw == "EVT ERROR t=40.00 codigo=E_ATASCO orden=- tramo=1/1"
    _wait(lambda: c.get("/api/robot").json()["error"] == "E_ATASCO", msg="error in status")


def _robot_event_any(S, kind):
    with S() as db:
        return db.scalar(select(RobotEvent).where(RobotEvent.event_type == kind))


def test_admin_websocket_gets_robot_status_and_order_updates(robot):
    c, _, _ = robot
    o = _new_order(c)
    with c.websocket_connect("/api/ws/admin") as ws:
        types = [ws.receive_json()["type"] for _ in range(3)]
        assert types == ["hello", "snapshot", "robot.status"]
        assert c.post(f"/api/orders/{o['id']}/dispatch").status_code == 200
        seen = {}
        for _ in range(10):
            m = ws.receive_json()
            seen.setdefault(m["type"], m["data"])
            if "order.updated" in seen and seen.get("robot.status", {}).get("state", "").startswith("RECORRIDO"):
                break
            if m["type"] == "robot.status" and m["data"]["state"].startswith("RECORRIDO"):
                seen["robot.status"] = m["data"]
        assert seen["order.updated"]["status"] == "DESPACHADA"
        assert seen["robot.status"]["state"] == "RECORRIDO_MESA_2"
