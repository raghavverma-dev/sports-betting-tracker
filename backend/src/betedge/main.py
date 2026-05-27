"""FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from betedge import __version__
from betedge.api import backtest as backtest_router
from betedge.api import bets as bets_router
from betedge.api import health as health_router
from betedge.api import odds as odds_router
from betedge.config import get_settings


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(message)s",
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _configure_logging(settings.log_level)
    log = structlog.get_logger()
    log.info("betedge.startup", environment=settings.environment, version=__version__)
    yield
    log.info("betedge.shutdown")


app = FastAPI(
    title="BetEdge API",
    description=(
        "Backend for the BetEdge sports-forecasting platform: live-odds "
        "proxy, de-vig + EV ranking, bet history, and a backtesting "
        "engine with forecast-quality and portfolio metrics."
    ),
    version=__version__,
    lifespan=lifespan,
)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router.router)
app.include_router(bets_router.router)
app.include_router(odds_router.router)
app.include_router(backtest_router.router)
