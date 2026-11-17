"""Database engine and session. Tables arrive in Phase 2."""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 3},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


def check_db() -> dict:
    """Ping PostgreSQL and return its clock (all timestamps will come from UTC)."""
    try:
        with engine.connect() as conn:
            now = conn.execute(text("SELECT now()")).scalar_one()
        return {"status": "ok", "db_time": now.isoformat()}
    except Exception as ex:  # report, never crash the health endpoint
        return {"status": "error", "detail": str(ex).splitlines()[0]}
