"""Backtest API: run new backtests, list past runs, fetch run detail."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from betedge.backtest.engine import EngineConfig, run_backtest
from betedge.backtest.strategies import build_strategy
from betedge.db import get_session
from betedge.models import BacktestBet, BacktestRun
from betedge.schemas import (
    BacktestRequest,
    BacktestRunDetail,
    BacktestRunOut,
    CalibrationBin,
)

router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.get("/runs", response_model=list[BacktestRunOut])
def list_runs(
    limit: int = 50,
    session: Session = Depends(get_session),
) -> list[BacktestRun]:
    stmt = select(BacktestRun).order_by(BacktestRun.started_at.desc()).limit(limit)
    return list(session.scalars(stmt).all())


@router.post("/runs", response_model=BacktestRunDetail, status_code=status.HTTP_201_CREATED)
def create_run(
    req: BacktestRequest,
    session: Session = Depends(get_session),
) -> BacktestRunDetail:
    strategy = build_strategy(
        req.strategy,
        min_ev=req.min_ev,
        kelly_fraction=req.kelly_fraction,
        max_stake_percent=req.max_stake_percent,
    )
    probability_source = _build_probability_source(req, session)
    config = EngineConfig(
        strategy=strategy,
        sport=req.sport,
        market=req.market,
        season=req.season,
        start_date=req.start_date,
        end_date=req.end_date,
        initial_bankroll=req.initial_bankroll,
        probability_source=probability_source,
    )
    result = run_backtest(session, config)
    if result.run_id is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Backtest ran but was not persisted — check server logs.",
        )
    return _run_to_detail(session, result.run_id, probability_source=req.probability_source)


def _build_probability_source(req: BacktestRequest, session: Session):  # type: ignore[no-untyped-def]
    """Construct the forecast source. The model source is optional (needs the
    'ml' extras + a trained artifact + a matching sport); surface its failure
    modes as a 400 the UI can show, not a 500."""
    if req.probability_source != "model":
        from betedge.backtest.engine import MarketProbabilitySource

        return MarketProbabilitySource()
    try:
        from betedge.ml.model import ModelProbabilitySource

        return ModelProbabilitySource(session, sport=req.sport, season=req.season)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except RuntimeError as exc:  # ml extras not installed
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/runs/{run_id}", response_model=BacktestRunDetail)
def run_detail(
    run_id: int,
    session: Session = Depends(get_session),
) -> BacktestRunDetail:
    run = session.get(BacktestRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backtest run not found")
    return _run_to_detail(session, run_id)


def _run_to_detail(
    session: Session,
    run_id: int,
    *,
    probability_source: str = "market",
) -> BacktestRunDetail:
    run = session.get(BacktestRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backtest run not found")

    calibration = None
    if run.calibration_json:
        raw = json.loads(run.calibration_json)
        calibration = [
            CalibrationBin(
                bin_lower=c["bin_lower"],
                bin_upper=c["bin_upper"],
                predicted_mean=c["predicted_mean"],
                empirical_mean=c["empirical_mean"] if c.get("empirical_mean") is not None else 0.0,
                count=c["count"],
            )
            for c in raw
        ]

    bets = list(
        session.scalars(
            select(BacktestBet)
            .where(BacktestBet.run_id == run_id)
            .order_by(BacktestBet.id.asc())
        ).all()
    )
    equity_curve: list[tuple[datetime, float]] = [(run.start_date, run.initial_bankroll)]
    if bets:
        from betedge.models import HistoricalGame

        game_ids = [b.game_id for b in bets]
        games = {
            g.id: g
            for g in session.scalars(
                select(HistoricalGame).where(HistoricalGame.id.in_(game_ids))
            ).all()
        }
        for bet in bets:
            game = games.get(bet.game_id)
            stamp = game.commence_time if game is not None else run.finished_at or datetime.now(UTC)
            equity_curve.append((stamp, bet.bankroll_after))

    return BacktestRunDetail(
        id=run.id,
        strategy=run.strategy,
        sport=run.sport,
        market=run.market,
        start_date=run.start_date,
        end_date=run.end_date,
        started_at=run.started_at,
        finished_at=run.finished_at,
        games_evaluated=run.games_evaluated,
        bets_placed=run.bets_placed,
        brier_score=run.brier_score,
        log_loss=run.log_loss,
        initial_bankroll=run.initial_bankroll,
        final_bankroll=run.final_bankroll,
        roi=run.roi,
        max_drawdown=run.max_drawdown,
        calibration=calibration,
        equity_curve=equity_curve,
        probability_source="model" if probability_source == "model" else "market",
    )
