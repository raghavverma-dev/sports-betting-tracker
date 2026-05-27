"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-16 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sport", sa.String(length=16), nullable=False),
        sa.Column("bet_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("event", sa.String(length=256), nullable=False),
        sa.Column("selection", sa.String(length=256), nullable=False),
        sa.Column("odds", sa.Integer(), nullable=False),
        sa.Column("stake", sa.Float(), nullable=False),
        sa.Column("potential_payout", sa.Float(), nullable=False),
        sa.Column("actual_payout", sa.Float(), nullable=True),
        sa.Column("placed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sportsbook", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("estimated_probability", sa.Float(), nullable=True),
        sa.Column("implied_probability", sa.Float(), nullable=False),
        sa.Column("expected_value", sa.Float(), nullable=True),
        sa.Column("kelly_stake", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_bets_sport", "bets", ["sport"])
    op.create_index("ix_bets_status", "bets", ["status"])

    op.create_table(
        "bankroll_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("delta", sa.Float(), nullable=False),
        sa.Column("balance_after", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column(
            "bet_id",
            sa.Integer(),
            sa.ForeignKey("bets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_bankroll_events_occurred_at", "bankroll_events", ["occurred_at"])

    op.create_table(
        "historical_games",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("external_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("sport", sa.String(length=16), nullable=False),
        sa.Column("season", sa.String(length=16), nullable=False),
        sa.Column("commence_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("home_team", sa.String(length=96), nullable=False),
        sa.Column("away_team", sa.String(length=96), nullable=False),
        sa.Column("home_score", sa.Integer(), nullable=False),
        sa.Column("away_score", sa.Integer(), nullable=False),
        sa.Column("winner", sa.String(length=8), nullable=False),
    )
    op.create_index("ix_historical_games_external_id", "historical_games", ["external_id"])
    op.create_index("ix_historical_games_sport", "historical_games", ["sport"])
    op.create_index("ix_historical_games_commence_time", "historical_games", ["commence_time"])

    op.create_table(
        "historical_odds",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "game_id",
            sa.Integer(),
            sa.ForeignKey("historical_games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("book", sa.String(length=64), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("outcome", sa.String(length=96), nullable=False),
        sa.Column("american_odds", sa.Integer(), nullable=False),
        sa.Column("point", sa.Float(), nullable=True),
        sa.UniqueConstraint(
            "game_id", "book", "market", "outcome", name="uq_hist_odds_game_book_market_outcome"
        ),
    )
    op.create_index("ix_historical_odds_game_id", "historical_odds", ["game_id"])

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("sport", sa.String(length=16), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False, server_default="h2h"),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("games_evaluated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bets_placed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("brier_score", sa.Float(), nullable=True),
        sa.Column("log_loss", sa.Float(), nullable=True),
        sa.Column("calibration_json", sa.Text(), nullable=True),
        sa.Column("initial_bankroll", sa.Float(), nullable=False),
        sa.Column("final_bankroll", sa.Float(), nullable=True),
        sa.Column("roi", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
    )

    op.create_table(
        "backtest_bets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("backtest_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "game_id",
            sa.Integer(),
            sa.ForeignKey("historical_games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("selection", sa.String(length=96), nullable=False),
        sa.Column("american_odds", sa.Integer(), nullable=False),
        sa.Column("book", sa.String(length=64), nullable=False),
        sa.Column("predicted_probability", sa.Float(), nullable=False),
        sa.Column("market_probability", sa.Float(), nullable=False),
        sa.Column("stake", sa.Float(), nullable=False),
        sa.Column("payout", sa.Float(), nullable=False),
        sa.Column("outcome", sa.Float(), nullable=False),
        sa.Column("bankroll_after", sa.Float(), nullable=False),
    )
    op.create_index("ix_backtest_bets_run_id", "backtest_bets", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_backtest_bets_run_id", table_name="backtest_bets")
    op.drop_table("backtest_bets")
    op.drop_table("backtest_runs")
    op.drop_index("ix_historical_odds_game_id", table_name="historical_odds")
    op.drop_table("historical_odds")
    op.drop_index("ix_historical_games_commence_time", table_name="historical_games")
    op.drop_index("ix_historical_games_sport", table_name="historical_games")
    op.drop_index("ix_historical_games_external_id", table_name="historical_games")
    op.drop_table("historical_games")
    op.drop_index("ix_bankroll_events_occurred_at", table_name="bankroll_events")
    op.drop_table("bankroll_events")
    op.drop_index("ix_bets_status", table_name="bets")
    op.drop_index("ix_bets_sport", table_name="bets")
    op.drop_table("bets")
