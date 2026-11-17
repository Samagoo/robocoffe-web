"""Database engine, session and declarative base."""
from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 3},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


# Deterministic constraint names, so Alembic migrations can always refer to them
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db() -> dict:
    """Ping PostgreSQL; report its clock and the applied migration revision."""
    try:
        with engine.connect() as conn:
            now = conn.execute(text("SELECT now()")).scalar_one()
            try:
                rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
            except Exception:
                rev = None      # migrations never ran
        return {"status": "ok", "db_time": now.isoformat(), "schema_revision": rev}
    except Exception as ex:  # report, never crash the health endpoint
        return {"status": "error", "detail": str(ex).splitlines()[0]}
