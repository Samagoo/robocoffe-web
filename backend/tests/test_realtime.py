import asyncio
import time
from datetime import datetime, timedelta

from app.realtime.manager import ConnectionManager

WS = "/api/ws/admin"


def _order(client, **kw):
    r = client.post("/api/orders", json={"product_code": "C1", "table_number": 1} | kw)
    assert r.status_code == 201, r.text
    return r.json()


def _handshake(ws):
    hello = ws.receive_json()
    snap = ws.receive_json()
    assert hello["type"] == "hello" and snap["type"] == "snapshot"
    return hello, snap


def test_connect_sends_hello_then_snapshot_with_existing_orders(client):
    existing = _order(client, customer_name="antes")
    with client.websocket_connect(WS) as ws:
        hello, snap = _handshake(ws)
        assert "version" in hello["data"]
        folios = [o["folio"] for o in snap["data"]["orders"]]
        assert existing["folio"] in folios


def test_new_order_is_broadcast_with_same_payload_as_rest(client):
    with client.websocket_connect(WS) as ws:
        _handshake(ws)
        created = _order(client, customer_name="Ana")
        msg = ws.receive_json()
        assert msg["type"] == "order.created"
        assert msg["data"] == created


def test_every_connected_client_receives_it(client):
    # Connect one after the other: in tests both snapshots share ONE session, which can't be
    # used concurrently (in production each snapshot opens its own session).
    with client.websocket_connect(WS) as a:
        _handshake(a)
        with client.websocket_connect(WS) as b:
            _handshake(b)
            created = _order(client)
            assert a.receive_json()["data"]["id"] == created["id"]
            assert b.receive_json()["data"]["id"] == created["id"]


def test_envelope_timestamp_is_utc(client):
    with client.websocket_connect(WS) as ws:
        hello, _ = _handshake(ws)
        assert datetime.fromisoformat(hello["ts"]).utcoffset() == timedelta(0)


def test_ping_pong_and_unknown_messages(client):
    with client.websocket_connect(WS) as ws:
        _handshake(ws)
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"
        ws.send_text("not json")
        assert ws.receive_json()["type"] == "error"


def test_health_counts_admin_clients(client):
    assert client.get("/api/health").json()["realtime"]["admin_clients"] == 0
    with client.websocket_connect(WS) as ws:
        _handshake(ws)
        assert client.get("/api/health").json()["realtime"]["admin_clients"] == 1
    for _ in range(50):                               # server-side cleanup runs right after close
        if client.get("/api/health").json()["realtime"]["admin_clients"] == 0:
            break
        time.sleep(0.02)
    assert client.get("/api/health").json()["realtime"]["admin_clients"] == 0


def test_rest_still_works_without_any_websocket_client(client):
    assert _order(client)["folio"].startswith("P-")


# ---------------------------------------------------------------- manager unit tests
class _FakeWS:
    def __init__(self, fail=False):
        self.fail, self.sent = fail, []

    async def send_json(self, msg):
        if self.fail:
            raise RuntimeError("socket closed")
        self.sent.append(msg)


def test_broadcast_drops_failing_clients_and_keeps_the_rest():
    m = ConnectionManager()
    good, bad = _FakeWS(), _FakeWS(fail=True)
    m.add(good)
    m.add(bad)
    asyncio.run(m.broadcast("order.created", {"id": 1}))
    assert m.count == 1
    assert good.sent[0]["type"] == "order.created" and good.sent[0]["data"] == {"id": 1}
