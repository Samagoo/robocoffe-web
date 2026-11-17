"""RoboCoffee backend — FastAPI entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import health, orders, robot, ws
from .config import settings
from .db import get_session_factory
from .order_config import get_order_config
from .robot.link import RobotLink

# Fail at startup (not at the first order) if order_config.json is invalid
get_order_config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    factory = app.dependency_overrides.get(get_session_factory, get_session_factory)()
    link = RobotLink(settings.robot_host, settings.robot_port, factory,
                     client_dir=settings.robot_client_dir, poll_s=settings.robot_poll_s)
    app.state.robot_link = link
    if settings.robot_enabled:
        await link.start()
    try:
        yield
    finally:
        await link.stop()


app = FastAPI(title="RoboCoffee Platform", version=settings.app_version, lifespan=lifespan)

# Every route lives under /api (the Vite dev server proxies /api, including WebSockets, to here)
app.include_router(health.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(robot.router, prefix="/api")
app.include_router(ws.router, prefix="/api")
