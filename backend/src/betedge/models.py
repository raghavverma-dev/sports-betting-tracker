"""SQLAlchemy 2.0 ORM models.

Schema at a glance:
  bets              -- manually-tracked or auto-placed bets (live use)
  bankroll_events   -- append-only ledger; current bankroll is derived
  historical_games  -- seed data: completed games with final scores
  historical_odds   -- closing odds per game/book/market/outcome
  backtest_runs     -- one row per invocation of the backtest engine
  backtest_bets     -- per-game simulated bets belonging to a run
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------- Live / user-facing ----------


class Bet(Base, TimestampMixin):
    __tablename__ = "bets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sport: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    bet_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    event: Mapped[str] = mapped_column(String(256), nullable=False)
    selection: Mapped[str] = mapped_column(String(256), nullable=False)
    odds: Mapped[int] = mapped_column(Integer, nullable=False, doc="American odds")
    stake: Mapped[float] = mapped_column(Float, nullable=False)
    potential_payout: Mapped[float] = mapped_column(Float, nullable=False)
    actual_payout: Mapped[float | None] = mapped_column(Float)
    placed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sportsbook: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    estimated_probability: Mapped[float | None] = mapped_column(Float)
    implied_probability: Mapped[float] = mapped_column(Float, nullable=False)
    expected_value: Mapped[float | None] = mapped_column(Float)
    kelly_stake: Mapped[float | None] = mapped_column(Float)


class BankrollEvent(Base):
    """Append-only ledger of bankroll changes.

    Current bankroll = initial + sum(delta). Storing events (rather than
    snapshots) makes the history auditable and lets the UI draw a true
    time-series chart.
    """

    __tablename__ = "bankroll_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    delta: Mapped[float] = mapped_column(Float, nullable=False)
    balance_after: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    bet_id: Mapped[int | None] = mapped_column(ForeignKey("bets.id", ondelete="SET NULL"))


# ---------- Historical / backtest corpus ----------


class HistoricalGame(Base):
    __tablename__ = "historical_games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    sport: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    season: Mapped[str] = mapped_column(String(16), nullable=False)
    commence_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    home_team: Mapped[str] = mapped_column(String(96), nullable=False)
    away_team: Mapped[str] = mapped_column(String(96), nullable=False)
    home_score: Mapped[int] = mapped_column(Integer, nullable=False)
    away_score: Mapped[int] = mapped_column(Integer, nullable=False)
    # 'home' | 'away' | 'draw'
    winner: Mapped[str] = mapped_column(String(8), nullable=False)

    odds: Mapped[list[HistoricalOdds]] = relationship(
        back_populates="game", cascade="all, delete-orphan", lazy="selectin"
    )


class HistoricalOdds(Base):
    __tablename__ = "historical_odds"
    __table_args__ = (
        UniqueConstraint(
            "game_id", "book", "market", "outcome", name="uq_hist_odds_game_book_market_outcome"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("historical_games.id", ondelete="CASCADE"), nullable=False, index=True
    )
    book: Mapped[str] = mapped_column(String(64), nullable=False)
    market: Mapped[str] = mapped_column(String(16), nullable=False, doc="h2h | spreads | totals")
    outcome: Mapped[str] = mapped_column(String(96), nullable=False)
    # American odds at market close
    american_odds: Mapped[int] = mapped_column(Integer, nullable=False)
    point: Mapped[float | None] = mapped_column(Float)

    game: Mapped[HistoricalGame] = relationship(back_populates="odds")


# ---------- Backtest results ----------


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    sport: Mapped[str] = mapped_column(String(16), nullable=False)
    market: Mapped[str] = mapped_column(String(16), nullable=False, default="h2h")
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    params_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    games_evaluated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bets_placed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Forecast-quality metrics (from predictions, independent of betting)
    brier_score: Mapped[float | None] = mapped_column(Float)
    log_loss: Mapped[float | None] = mapped_column(Float)
    # JSON-encoded 10-bin calibration curve
    calibration_json: Mapped[str | None] = mapped_column(Text)

    # Simulated-portfolio metrics
    initial_bankroll: Mapped[float] = mapped_column(Float, nullable=False)
    final_bankroll: Mapped[float | None] = mapped_column(Float)
    roi: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)

    bets: Mapped[list[BacktestBet]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class BacktestBet(Base):
    __tablename__ = "backtest_bets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    game_id: Mapped[int] = mapped_column(
        ForeignKey("historical_games.id", ondelete="CASCADE"), nullable=False
    )
    selection: Mapped[str] = mapped_column(String(96), nullable=False)
    american_odds: Mapped[int] = mapped_column(Integer, nullable=False)
    book: Mapped[str] = mapped_column(String(64), nullable=False)
    predicted_probability: Mapped[float] = mapped_column(Float, nullable=False)
    market_probability: Mapped[float] = mapped_column(Float, nullable=False)
    stake: Mapped[float] = mapped_column(Float, nullable=False)
    payout: Mapped[float] = mapped_column(Float, nullable=False)
    # 1 = win, 0 = loss, 0.5 = push (rare in h2h)
    outcome: Mapped[float] = mapped_column(Float, nullable=False)
    bankroll_after: Mapped[float] = mapped_column(Float, nullable=False)

    run: Mapped[BacktestRun] = relationship(back_populates="bets")
