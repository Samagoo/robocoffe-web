"""GET /api/health — status of every subsystem the platform depends on."""
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from ..config import settings
from ..db import check_db
from ..realtime.manager import admin_feed

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request):
    db = check_db()
    robot = request.app.state.robot_link.status()
    return {
        "status": "ok" if db["status"] == "ok" else "degraded",
        "version": settings.app_version,
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "database": db,
        # ClienteRobot link to main_real.py / servidor_simulado.py (details: GET /api/robot)
        "robot": {
            "host": settings.robot_host,
            "port": settings.robot_port,
            "link": robot["link"] if settings.robot_enabled else "disabled",
            "state": robot["state"],
        },
        # Scale-bridge phase: readings forwarded from the Bluetooth COM port
        "scale": {"ingestion": "not_implemented"},
        "realtime": {"admin_clients": admin_feed.count},
    }
