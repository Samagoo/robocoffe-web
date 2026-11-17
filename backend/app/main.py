"""RoboCoffee backend — FastAPI entry point."""
from fastapi import FastAPI

from .api import health
from .config import settings

app = FastAPI(title="RoboCoffee Platform", version=settings.app_version)

# Every REST route lives under /api (the Vite dev server proxies /api to here)
app.include_router(health.router, prefix="/api")
