"""RoboCoffee backend — FastAPI entry point."""
from fastapi import FastAPI

from .api import health, orders, ws
from .config import settings
from .order_config import get_order_config

app = FastAPI(title="RoboCoffee Platform", version=settings.app_version)

# Fail at startup (not at the first order) if order_config.json is invalid
get_order_config()

# Every route lives under /api (the Vite dev server proxies /api, including WebSockets, to here)
app.include_router(health.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(ws.router, prefix="/api")
