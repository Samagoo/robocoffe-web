"""The platform's ONLY connection to the robot subsystem: a thin wrapper around the robot
team's existing ClienteRobot (robot/cliente/robocoffe_cliente.py, imported unchanged).

ClienteRobot already does the protocol work: one TCP connection to main_real.py /
servidor_simulado.py on port 9000, automatic reconnection, increasing ids, retries with the
SAME id, ESTADO on (re)connect, and a queue with every line. This module only adds the
platform side:
  * store every EVT line in robot_events (UTC receive time), linked to its order by robot_msg_id;
  * dispatch: reserve an id on the order -> ClienteRobot.ordenar() -> persist the outcome;
  * publish robot.status / order.updated to admin pages.
"""
import asyncio
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..api.orders import order_json
from ..models import Order, RobotEvent
from ..order_config import get_order_config
from ..realtime.manager import admin_feed, publish_order
from ..services.orders import mark_dispatched, record_event

log = logging.getLogger("robocoffee.robot")

STATUS_HEARTBEAT_S = 5.0   # re-send robot.status at least this often (keeps "last heard" fresh)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_cliente_robot(client_dir: str):
    """Import ClienteRobot from the robot team's folder. None if it isn't there."""
    if client_dir and Path(client_dir).is_dir() and client_dir not in sys.path:
        sys.path.insert(0, client_dir)
    try:
        from robocoffe_cliente import ClienteRobot  # noqa: PLC0415  (robot team's module)
        return ClienteRobot
    except ImportError as ex:
        log.warning("robocoffe_cliente not importable from %r: %s", client_dir, ex)
        return None


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _msg_id(v):
    return int(v) if isinstance(v, str) and v.isdigit() else None


@dataclass
class DispatchOutcome:
    http_status: int          # 200 accepted, 409 rejected by the robot, 504 no answer
    ok: bool
    robot_msg_id: int
    reason: str               # robot code (OCUPADO, FUERA_DE_BASE, ...) or SIN_RESPUESTA; "" if ok
    robot_state: str | None   # state the robot reported in OK ORDEN
    order: dict


class RobotLink:
    def __init__(self, host: str, port: int, session_factory: Callable[[], Session],
                 client_dir: str, poll_s: float = 2.0):
        self.host, self.port = host, port
        self.session_factory = session_factory
        self.client_dir = client_dir
        self.poll_s = poll_s
        self.client = None
        self.last_message_at: datetime | None = None
        self._queue = None
        self._tasks: list[asyncio.Task] = []
        self._dispatch_lock: asyncio.Lock | None = None
        self._last_status_key = None
        self._last_status_sent = 0.0

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        cls = load_cliente_robot(self.client_dir)
        if cls is None:
            return
        self._dispatch_lock = asyncio.Lock()
        self.client = cls(self.host, self.port)
        self._queue = self.client.suscribir(maximo=1000)
        await self.client.iniciar()
        self._tasks = [asyncio.create_task(self._consume(), name="robot-consume")]
        if self.poll_s > 0:
            self._tasks.append(asyncio.create_task(self._poll(), name="robot-poll"))
        log.info("robot link started -> %s:%s", self.host, self.port)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []
        if self.client is not None:
            await self.client.cerrar()

    # ------------------------------------------------------------ status
    def status(self) -> dict:
        """Robot status for the API / WebSocket, from ClienteRobot.resumen()."""
        base = {"host": self.host, "port": self.port,
                "last_message_at": self.last_message_at.isoformat() if self.last_message_at else None}
        if self.client is None:
            return base | {"link": "unavailable", "state": None, "robot_order": None, "battery_v": None,
                           "pose": None, "error": None, "free": False}
        r = self.client.resumen()
        pose = r.get("pose")
        return base | {
            "link": "connected" if r["conectado"] else "disconnected",
            "state": r["estado"],
            "robot_order": _msg_id(r["orden"]),          # = orders.robot_msg_id of the current trip
            "battery_v": r["bateria"],
            "pose": {"x": pose[0], "y": pose[1], "th": pose[2]} if pose else None,
            "error": r["error"],
            "free": bool(self.client.libre),
        }

    async def _publish_status(self, force: bool = False) -> None:
        s = self.status()
        key = {k: v for k, v in s.items() if k != "last_message_at"}
        now = asyncio.get_running_loop().time()
        if force or key != self._last_status_key or now - self._last_status_sent >= STATUS_HEARTBEAT_S:
            self._last_status_key, self._last_status_sent = key, now
            await admin_feed.broadcast("robot.status", s)

    # ------------------------------------------------------------ incoming lines
    async def _consume(self) -> None:
        while True:
            d = await self._queue.get()
            try:
                await self._handle(d)
            except Exception:
                log.exception("robot message not processed: %r", d)

    async def _handle(self, d: dict) -> None:
        at = utcnow()
        if d.get("tipo") == "CONEXION":
            await asyncio.to_thread(self._store_connection, d["conectado"], at)
            await self._publish_status(force=True)
            return
        self.last_message_at = at
        if d.get("tipo") == "EVT":
            changed = await asyncio.to_thread(self._store_event, d, at)
            if changed is not None:
                await publish_order("order.updated", changed)
        await self._publish_status()

    def _store_connection(self, connected: bool, at: datetime) -> None:
        """Platform-side event: link to the robot software went up/down (downtime analysis)."""
        with self.session_factory() as db:
            db.add(RobotEvent(received_at=at, event_type="CONEXION", fields={"conectado": connected},
                              raw=f"[platform] CONEXION conectado={int(connected)} {self.host}:{self.port}"))
            db.commit()

    def _store_event(self, d: dict, at: datetime) -> dict | None:
        """Persist one EVT line. If it proves the robot started an order whose OK reply was
        lost, confirm the dispatch. Returns the updated order JSON, or None."""
        c = d.get("campos", {})
        msg_id = _msg_id(c.get("orden"))
        with self.session_factory() as db:
            order = None
            if msg_id is not None:
                order = db.query(Order).filter(Order.robot_msg_id == msg_id).with_for_update().one_or_none()
            db.add(RobotEvent(received_at=at, event_type=d["nombre"][:20], robot_t=_float(c.get("t")),
                              robot_msg_id=msg_id, order_id=order.id if order else None,
                              fields=c, raw=d.get("linea", "")))
            changed = False
            if (order is not None and d["nombre"] == "TRANSICION"
                    and str(c.get("a", "")).startswith("RECORRIDO_MESA")):
                changed = mark_dispatched(db, order, at, "confirmed_by_robot_event", "robot")
            db.commit()
            return order_json(order) if changed else None

    async def _poll(self) -> None:
        """ESTADO is a query: the robot always answers it and never changes state for it."""
        while True:
            await asyncio.sleep(self.poll_s)
            if self.client.conectado:
                try:
                    await self.client.consultar_estado()
                except Exception:
                    log.exception("ESTADO poll failed")

    # ------------------------------------------------------------ dispatch
    async def dispatch(self, order_id: int) -> DispatchOutcome:
        if self.client is None:
            raise HTTPException(503, "robot client unavailable (robocoffe_cliente.py not found)")
        async with self._dispatch_lock:            # one ORDEN in flight at a time
            if not self.client.conectado:
                raise HTTPException(503, f"robot software not connected ({self.host}:{self.port})")
            msg_id = self.client.nuevo_id()
            table, prev_id = await asyncio.to_thread(self._reserve, order_id, msg_id)
            sent_at = utcnow()
            r = await self.client.ordenar(table, id_=msg_id)
            if not r.ok and r.motivo == "SIN_RESPUESTA":
                await self.client.consultar_estado()   # maybe only the reply was lost
                if self.client.orden == str(msg_id):
                    r.ok, r.motivo = True, ""
            payload = await asyncio.to_thread(self._finish, order_id, r, sent_at, prev_id)
        await publish_order("order.updated", payload)
        if r.ok:
            return DispatchOutcome(200, True, msg_id, "", r.campos.get("estado"), payload)
        code = 504 if r.motivo == "SIN_RESPUESTA" else 409
        return DispatchOutcome(code, False, msg_id, r.motivo, None, payload)

    def _reserve(self, order_id: int, msg_id: int) -> tuple[int, int | None]:
        """Write the ORDEN id on the order BEFORE sending, so robot events that arrive
        before the OK reply can already be linked to it."""
        with self.session_factory() as db:
            order = db.get(Order, order_id, with_for_update=True)
            if order is None:
                raise HTTPException(404, f"order {order_id} not found")
            if order.dispatched_at is not None:
                raise HTTPException(409, f"{order.folio} was already dispatched")
            if order.status not in get_order_config().dispatch_from:
                raise HTTPException(409, f"{order.folio} has status {order.status}, which can't be dispatched")
            prev = order.robot_msg_id      # set only if an earlier attempt got no answer
            order.robot_msg_id = msg_id
            db.commit()
            return order.table_number, prev

    def _finish(self, order_id: int, r, sent_at: datetime, prev_id: int | None) -> dict:
        with self.session_factory() as db:
            order = db.get(Order, order_id, with_for_update=True)
            if r.ok:
                mark_dispatched(db, order, sent_at, f"robot_ok:{r.campos.get('estado', '-')}", "admin")
            elif r.motivo == "SIN_RESPUESTA":
                # Keep the id: if the robot did get it, its TRANSICION event will confirm the dispatch
                record_event(db, order, order.status, "dispatch_no_reply", "admin")
            else:
                order.robot_msg_id = prev_id          # id rejected: never used by the robot
                record_event(db, order, order.status, f"dispatch_rejected:{r.motivo}", "admin")
            db.commit()
            db.refresh(order)
            return order_json(order)
