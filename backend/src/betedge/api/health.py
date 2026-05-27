"""Liveness/readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from betedge import __version__
from betedge.db import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
def liveness() -> dict[str, str]:
    """Liveness probe — returns 200 if the process is running."""
    return {"status": "ok", "version": __version__}


@router.get("/ready")
def readiness(session: Session = Depends(get_session)) -> dict[str, str]:
    """Readiness probe — verifies the DB is reachable.

    Kubernetes / Fly.io use this to decide whether to route traffic.
    """
    session.execute(text("SELECT 1"))
    return {"status": "ready"}
