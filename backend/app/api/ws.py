"""WebSocket /api/ws/admin: live order feed for the admin page (protocol: docs/websocket.md)."""
import json
from collections.abc import Callable

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_session_factory
from ..realtime.manager import admin_feed
from .orders import order_json, select_orders

router = APIRouter(tags=["realtime"])

SNAPSHOT_LIMIT = 100


def _snapshot(session_factory: Callable[[], Session]) -> list[dict]:
    with session_factory() as db:
        return [order_json(o) for o in select_orders(db, SNAPSHOT_LIMIT)]


@router.websocket("/ws/admin")
async def admin_ws(websocket: WebSocket, session_factory=Depends(get_session_factory)):
    await websocket.accept()
    # Register BEFORE taking the snapshot: an order created in between arrives as
    # order.created and/or in the snapshot. The client merges by id, so duplicates are harmless.
    admin_feed.add(websocket)
    try:
        await admin_feed.send(websocket, "hello",
                              {"version": settings.app_version, "snapshot_limit": SNAPSHOT_LIMIT})
        orders = await run_in_threadpool(_snapshot, session_factory)
        await admin_feed.send(websocket, "snapshot", {"orders": orders})
        await admin_feed.send(websocket, "robot.status", websocket.app.state.robot_link.status())

        while True:                                   # client -> server: only "ping" for now
            text = await websocket.receive_text()
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                msg = None
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await admin_feed.send(websocket, "pong", {})
            else:
                await admin_feed.send(websocket, "error", {"detail": "unknown message"})
    except WebSocketDisconnect:
        pass
    finally:
        admin_feed.remove(websocket)
