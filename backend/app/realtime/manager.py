"""WebSocket connections and broadcasting (protocol: docs/websocket.md).

In memory, one backend process: fine for a single Windows PC. With several
uvicorn workers each would only see its own clients.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("robocoffee.realtime")

SEND_TIMEOUT_S = 5.0   # a frozen browser tab must not block broadcasts to the others


def envelope(msg_type: str, data: Any) -> dict:
    """Every server->client message: {type, ts (UTC, ISO 8601), data}."""
    return {"type": msg_type, "ts": datetime.now(timezone.utc).isoformat(), "data": data}


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    @property
    def count(self) -> int:
        return len(self._clients)

    def add(self, ws: WebSocket) -> None:
        self._clients.add(ws)

    def remove(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def send(self, ws: WebSocket, msg_type: str, data: Any) -> None:
        await ws.send_json(envelope(msg_type, data))

    async def broadcast(self, msg_type: str, data: Any) -> None:
        """Send to every connected client; drop the ones that fail."""
        msg = envelope(msg_type, data)
        for ws in list(self._clients):
            try:
                await asyncio.wait_for(ws.send_json(msg), SEND_TIMEOUT_S)
            except Exception as ex:
                log.info("dropping websocket client: %r", ex)
                self.remove(ws)


# Admin feed: orders. Phase 4 adds robot messages to the same channel.
admin_feed = ConnectionManager()


async def publish_order(msg_type: str, order_json: dict) -> None:
    """order.created / order.updated. Call AFTER the DB commit, with OrderOut JSON."""
    await admin_feed.broadcast(msg_type, order_json)
