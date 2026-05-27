"""Database engine, session factory, and FastAPI dependency.

Synchronous SQLAlchemy 2.0 is enough for this workload and keeps the
request path simpler. FastAPI will dispatch sync path operations to a
thread pool, so blocking DB calls don't starve the event loop.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from betedge.config import get_settings


def _make_engine() -> "Engine":  # type: ignore[name-defined]  # noqa: F821
    settings = get_settings()
    # pool_pre_ping avoids stale-connection errors after Postgres restarts
    # in dev; it's cheap and eliminates a class of flaky failures.
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
    )


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI dependency that yields a SQLAlchemy session per request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
