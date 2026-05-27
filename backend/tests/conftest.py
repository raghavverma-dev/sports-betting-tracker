"""Shared pytest fixtures.

Uses an in-memory SQLite DB so the suite can run without Docker or
Postgres. This means tests verify ORM logic and business rules but not
Postgres-specific behavior (which is fine — we have Alembic migrations
as the source of truth for schema).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from betedge.db import get_session
from betedge.main import app
from betedge.models import Base


@event.listens_for(Engine, "connect")
def _enable_sqlite_fk(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
    """SQLite doesn't enforce FKs by default; turn them on per connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture(scope="session")
def engine() -> Engine:
    # StaticPool shares a single connection across threads so that the
    # in-memory SQLite database (which is connection-scoped by default)
    # actually persists across sessions and across the TestClient's
    # request handling.
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    sess = maker()
    try:
        yield sess
    finally:
        sess.rollback()
        sess.close()
        # Clear per-test data so fixtures remain isolated.
        with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    """FastAPI test client with the DB dependency overridden to use the
    per-test session (so HTTP-level tests see the same data as the
    fixtures that seed it)."""

    def _override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = _override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
