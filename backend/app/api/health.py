"""GET /api/health — status of every subsystem the platform depends on."""
from datetime import datetime, timezone

from fastapi import APIRouter

from ..config import settings
from ..db import check_db
from ..realtime.manager import admin_feed

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    db = check_db()
    return {
        "status": "ok" if db["status"] == "ok" else "degraded",
        "version": settings.app_version,
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "database": db,
        # Phase 4: TCP link to main_real.py (PING / ESTADO)
        "robot": {
            "host": settings.robot_host,
            "port": settings.robot_port,
            "link": "not_implemented",
        },
        # Scale-bridge phase: readings forwarded from the Bluetooth COM port
        "scale": {"ingestion": "not_implemented"},
        "realtime": {"admin_clients": admin_feed.count},
    }
