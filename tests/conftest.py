"""Shared test fixtures and hermetic environment setup.

Environment variables are set before any ``app`` module is imported so the
cached settings singleton picks up test-safe values.

Integration tests run against a real PostgreSQL database (``vyapar_test`` on the
docker-compose ``db`` service, per the Testing & Deployment doc). Each test runs
inside an outer transaction that is rolled back on teardown, giving full
isolation without re-creating the schema per test. Unit tests that never request
a DB fixture do not touch Postgres.
"""

from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET", "test-secret-value-at-least-32-bytes-long!!")
os.environ.setdefault("JWT_ACCESS_TTL_SECONDS", "900")
os.environ.setdefault("MESSAGING_PROVIDER", "mock")
os.environ.setdefault("STORAGE_BACKEND", "memory")
# The notification listener writes via its own SessionLocal (independent of the
# rolled-back test session); disable the global subscription so the standard suite
# is unaffected. Notification behavior is tested with real committed sessions.
os.environ.setdefault("NOTIFICATIONS_ENABLED", "false")
os.environ.setdefault("DB_URL", "postgresql+psycopg://vyapar:vyapar@localhost:5432/vyapar_test")

from collections.abc import Iterator

import psycopg
import pytest
from app.config import get_settings
from app.db import Base, engine, get_session
from app.main import create_app
from app.providers import get_refresh_token_store
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def _ensure_test_database() -> None:
    """Create the ``vyapar_test`` database if it does not yet exist."""
    settings = get_settings()
    # Derive an admin URL to the default 'postgres' database.
    target_db = settings.db_url.rsplit("/", 1)[-1]
    admin_dsn = (
        settings.db_url.replace("postgresql+psycopg://", "postgresql://").rsplit("/", 1)[0]
        + "/postgres"
    )
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (target_db,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{target_db}"')


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    """Provision the test schema once for the whole session.

    Uses ``create_all`` from the ORM models for speed; the Alembic migration is
    verified independently against a clean database as a separate quality gate.
    """
    _ensure_test_database()
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A session wrapped in an outer transaction, rolled back after each test."""
    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def _reset_token_store() -> None:
    """Clear the in-memory refresh-token denylist between tests."""
    store = get_refresh_token_store()
    clear = getattr(store, "clear", None)
    if callable(clear):
        clear()


@pytest.fixture
def api(db_session: Session) -> Iterator[TestClient]:
    """TestClient whose request-scoped session is the rolled-back test session."""
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> TestClient:
    """Plain client for endpoints that do not touch the database."""
    return TestClient(create_app())
