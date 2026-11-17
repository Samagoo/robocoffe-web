"""Live state of the scale link (Phase 5.1). No decisions: the AdapterFSM comes in 5.2.

link values (GET /api/scale, WebSocket scale.status):
  offline      the bridge hasn't contacted the backend for scale_offline_s (or never did)
  port_closed  the bridge runs but its COM port is closed (adapter off, out of range, port busy)
  stale        port open but no reading for scale_stale_s: silence is NOT "0 g"
  live         readings arriving
"""
import asyncio
import time
from datetime import datetime, timezone

from ..realtime.manager import admin_feed

STATUS_HEARTBEAT_S = 5.0
READING_MIN_INTERVAL_S = 0.2     # cap scale.reading broadcasts at ~5 Hz


class ScaleMonitor:
    def __init__(self, stale_s: float = 3.0, offline_s: float = 15.0):
        self.stale_s, self.offline_s = stale_s, offline_s
        self.bridge: dict | None = None          # last /api/scale/link payload
        self.bridge_seen_mono: float | None = None
        self.bridge_seen_at: datetime | None = None
        self.last: dict | None = None            # newest reading {grams, raw, received_at, source}
        self.readings_received = 0
        self._last_key = None
        self._last_status_sent = 0.0
        self._last_reading_sent = 0.0
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------ inputs
    def _seen(self) -> None:
        self.bridge_seen_mono = time.monotonic()
        self.bridge_seen_at = datetime.now(timezone.utc)

    def on_link(self, payload: dict) -> None:
        self.bridge = payload
        self._seen()

    def on_readings(self, source: str, readings: list[dict]) -> None:
        """readings: [{grams, raw, received_at (datetime)}], any order."""
        self._seen()
        if self.bridge is None or self.bridge.get("source") != source:
            # readings imply an open port even if the first /link was missed
            self.bridge = {"source": source, "port_open": True, "detail": ""}
        self.readings_received += len(readings)
        newest = max(readings, key=lambda r: r["received_at"])
        if self.last is None or newest["received_at"] >= self.last["received_at"]:
            self.last = {"grams": newest["grams"], "raw": newest["raw"],
                         "received_at": newest["received_at"], "source": source}

    # ------------------------------------------------------------ outputs
    def status(self) -> dict:
        now = datetime.now(timezone.utc)
        age = (now - self.last["received_at"]).total_seconds() if self.last else None
        if self.bridge_seen_mono is None or time.monotonic() - self.bridge_seen_mono > self.offline_s:
            link = "offline"
        elif not self.bridge.get("port_open"):
            link = "port_closed"
        elif age is None or age > self.stale_s:
            link = "stale"
        else:
            link = "live"
        b = self.bridge or {}
        return {
            "link": link,
            "source": b.get("source"),
            "port_open": bool(b.get("port_open")),
            "detail": b.get("detail") or "",
            "bridge_version": b.get("bridge_version"),
            "bridge_counters": b.get("counters") or {},
            "bridge_queued": b.get("queued", 0),
            "bridge_seen_at": self.bridge_seen_at.isoformat() if self.bridge_seen_at else None,
            "last_reading": self.reading_json(),
            "age_s": round(age, 2) if age is not None else None,
            "readings_received": self.readings_received,
            "stale_after_s": self.stale_s,
        }

    def reading_json(self) -> dict | None:
        if not self.last:
            return None
        return {**self.last, "received_at": self.last["received_at"].isoformat()}

    async def publish_reading(self) -> None:
        now = time.monotonic()
        if self.last and now - self._last_reading_sent >= READING_MIN_INTERVAL_S:
            self._last_reading_sent = now
            await admin_feed.broadcast("scale.reading", self.reading_json())
        await self.publish_status()

    async def publish_status(self, force: bool = False) -> None:
        s = self.status()
        key = (s["link"], s["source"], s["port_open"], s["detail"])
        now = time.monotonic()
        if force or key != self._last_key or now - self._last_status_sent >= STATUS_HEARTBEAT_S:
            self._last_key, self._last_status_sent = key, now
            await admin_feed.broadcast("scale.status", s)

    # ------------------------------------------------------------ lifecycle
    async def _tick(self) -> None:
        """Detects live -> stale -> offline even when nothing arrives (silence has no event)."""
        while True:
            await asyncio.sleep(1.0)
            await self.publish_status()

    def start(self) -> None:
        self._task = asyncio.create_task(self._tick(), name="scale-monitor")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
