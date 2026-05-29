"""Pydantic request/response schemas.

Schemas are intentionally separate from ORM models so that:
  * we can evolve the wire format without touching the DB, and
  * we can hide internal fields (created_at, FK ids) from API clients.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------- Bets ----------

BetStatus = Literal["pending", "won", "lost", "push"]
BetType = Literal["moneyline", "spread", "over_under", "prop", "parlay", "teaser"]
Sport = Literal["NBA", "NFL", "MLB", "NHL", "NCAAF", "NCAAB", "MLS", "UFC"]


class BetCreate(BaseModel):
    sport: Sport
    bet_type: BetType
    event: str = Field(..., min_length=1, max_length=256)
    selection: str = Field(..., min_length=1, max_length=256)
    odds: int = Field(..., description="American odds")
    stake: float = Field(..., gt=0)
    sportsbook: str = Field(..., min_length=1, max_length=64)
    notes: str = ""
    estimated_probability: float | None = Field(None, ge=0, le=1)


class BetStatusUpdate(BaseModel):
    status: BetStatus


class BetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sport: Sport
    bet_type: BetType
    status: BetStatus
    event: str
    selection: str
    odds: int
    stake: float
    potential_payout: float
    actual_payout: float | None
    placed_at: datetime
    settled_at: datetime | None
    sportsbook: str
    notes: str
    estimated_probability: float | None
    implied_probability: float
    expected_value: float | None
    kelly_stake: float | None


# ---------- Bankroll ----------


class BankrollEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    delta: float
    balance_after: float
    reason: str
    bet_id: int | None


class BankrollSnapshot(BaseModel):
    current_balance: float
    initial_balance: float
    total_wagered: float
    total_returned: float
    history: list[BankrollEventOut]


# ---------- Live odds ----------


class BookOdds(BaseModel):
    book: str
    odds: int
    last_update: datetime | None = None


class RankedBetOut(BaseModel):
    id: str
    game_id: str
    sport: str
    event: str
    commence_time: datetime
    selection: str
    bet_type: str
    best_odds: int
    best_book: str
    avg_odds: int
    market_probability: float
    implied_probability: float
    ev: float
    num_books: int
    all_books: list[BookOdds]
    stale_warning: bool
    outlier_warning: bool
    stale_minutes: int = 0
    adjusted_ev: float | None = None
    adjusted_best_odds: int | None = None
    adjusted_best_book: str | None = None
    adjusted_market_probability: float | None = None


# ---------- Backtest ----------

StrategyName = Literal["market-baseline", "flat-ev-threshold", "kelly-ev-threshold"]


ProbabilitySourceName = Literal["market", "model"]


class BacktestRequest(BaseModel):
    strategy: StrategyName = "market-baseline"
    sport: Sport = "NBA"
    market: Literal["h2h"] = "h2h"
    # The forecast the strategy bets on: the de-vigged market price, or the
    # trained LightGBM model's P(home win). The model only serves held-out
    # games, so a model run needs a real season it was NOT trained on.
    probability_source: ProbabilitySourceName = "market"
    season: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    initial_bankroll: float = Field(default=1000.0, gt=0)
    min_ev: float = Field(default=0.0, description="EV percent threshold")
    kelly_fraction: float = Field(default=0.25, gt=0, le=1.0)
    max_stake_percent: float = Field(default=5.0, gt=0, le=100)


class CalibrationBin(BaseModel):
    bin_lower: float
    bin_upper: float
    predicted_mean: float
    empirical_mean: float
    count: int


class BacktestRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    strategy: str
    sport: str
    market: str
    start_date: datetime
    end_date: datetime
    started_at: datetime
    finished_at: datetime | None
    games_evaluated: int
    bets_placed: int
    brier_score: float | None
    log_loss: float | None
    initial_bankroll: float
    final_bankroll: float | None
    roi: float | None
    max_drawdown: float | None


class BacktestRunDetail(BacktestRunOut):
    calibration: list[CalibrationBin] | None = None
    equity_curve: list[tuple[datetime, float]] | None = None
    # Which forecast drove this run. Not a DB column — echoed from the
    # request so the UI can label a model run distinctly from a market one.
    probability_source: ProbabilitySourceName = "market"
