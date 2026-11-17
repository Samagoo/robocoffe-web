"""Test setup: a separate <db>_test database, rebuilt from the migrations on every run.

Your development data (and its folio sequence) is never touched. Each test runs inside a
transaction that is rolled back, so tests don't depend on each other.
"""
import os

import pytest
from sqlalchemy import create_engine, make_url, text

# Must happen BEFORE importing the app: its engine reads DATABASE_URL at import time
_dev_url = make_url(os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://robocoffee:robocoffee@localhost:5432/robocoffee"))
_test_url = _dev_url.set(database=f"{_dev_url.database}_test")
os.environ["DATABASE_URL"] = _test_url.render_as_string(hide_password=False)


def _recreate_test_database():
    admin = create_engine(_dev_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{_test_url.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{_test_url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Fresh database + `alembic upgrade head`: every run also tests the migrations."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    _recreate_test_database()
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture
def db(migrated_database):
    from sqlalchemy.orm import Session

    from app.db import engine

    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    outer.rollback()
    conn.close()


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient

    from contextlib import nullcontext

    from app.db import get_db, get_session_factory
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    # WebSocket snapshots use the same rolled-back test session (nullcontext: don't close it)
    app.dependency_overrides[get_session_factory] = lambda: (lambda: nullcontext(db))
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
