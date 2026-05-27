"""Click-based CLI for offline backtest runs.

Installed as the `betedge` console script via pyproject.toml.

Examples:
    betedge seed --num-games 400
    betedge backtest run --strategy market-baseline --sport NBA
    betedge backtest run --strategy kelly-ev-threshold --min-ev 2 --kelly-fraction 0.25
    betedge backtest list
    betedge data ingest-games --season 2023-24
    betedge data ingest-odds --season 2023-24 --path path/to/odds.csv
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import click

from betedge.backtest.engine import EngineConfig, run_backtest
from betedge.backtest.seed import SeedConfig, seed_historical_games
from betedge.backtest.strategies import build_strategy
from betedge.db import SessionLocal
from betedge.models import BacktestRun


@click.group()
def cli() -> None:
    """BetEdge offline tools."""


@cli.command("seed")
@click.option("--sport", default="NBA", show_default=True)
@click.option("--season", default="2024-2025", show_default=True)
@click.option("--num-games", default=400, show_default=True, type=int)
@click.option("--seed", "random_seed", default=42, show_default=True, type=int)
def seed_cmd(sport: str, season: str, num_games: int, random_seed: int) -> None:
    """Seed the database with synthetic historical games + closing odds."""
    with SessionLocal() as session:
        inserted = seed_historical_games(
            session,
            SeedConfig(sport=sport, season=season, num_games=num_games, seed=random_seed),
        )
    if inserted == 0:
        click.echo(f"[skip] {sport} {season} already seeded.")
    else:
        click.echo(f"[ok]   Seeded {inserted} games for {sport} {season}.")


@cli.group("backtest")
def backtest_group() -> None:
    """Run or inspect backtests."""


@backtest_group.command("run")
@click.option("--strategy", default="market-baseline", show_default=True)
@click.option("--sport", default="NBA", show_default=True)
@click.option("--market", default="h2h", show_default=True)
@click.option("--start", default=None, help="ISO date lower bound (inclusive).")
@click.option("--end", default=None, help="ISO date upper bound (inclusive).")
@click.option("--initial-bankroll", default=1000.0, show_default=True, type=float)
@click.option("--min-ev", default=2.0, show_default=True, type=float)
@click.option("--kelly-fraction", default=0.25, show_default=True, type=float)
@click.option("--max-stake-percent", default=5.0, show_default=True, type=float)
def backtest_run_cmd(
    strategy: str,
    sport: str,
    market: str,
    start: str | None,
    end: str | None,
    initial_bankroll: float,
    min_ev: float,
    kelly_fraction: float,
    max_stake_percent: float,
) -> None:
    """Run a backtest over the seeded corpus and print summary metrics."""
    strat = build_strategy(
        strategy,
        min_ev=min_ev,
        kelly_fraction=kelly_fraction,
        max_stake_percent=max_stake_percent,
    )
    config = EngineConfig(
        strategy=strat,
        sport=sport,
        market=market,
        start_date=datetime.fromisoformat(start) if start else None,
        end_date=datetime.fromisoformat(end) if end else None,
        initial_bankroll=initial_bankroll,
    )
    with SessionLocal() as session:
        result = run_backtest(session, config)

    click.echo(
        json.dumps(
            {
                "run_id": result.run_id,
                "strategy": strat.name,
                "games_evaluated": result.games_evaluated,
                "bets_placed": result.bets_placed,
                "initial_bankroll": initial_bankroll,
                "final_bankroll": result.final_bankroll,
                "roi_percent": round(result.roi, 3),
                "max_drawdown": round(result.max_drawdown, 4),
                "brier_score": round(result.brier_score, 5) if result.brier_score else None,
                "log_loss": round(result.log_loss_value, 5) if result.log_loss_value else None,
            },
            indent=2,
        )
    )


@backtest_group.command("list")
@click.option("--limit", default=20, show_default=True, type=int)
def backtest_list_cmd(limit: int) -> None:
    """Print the most recent backtest runs."""
    with SessionLocal() as session:
        runs = (
            session.query(BacktestRun)
            .order_by(BacktestRun.started_at.desc())
            .limit(limit)
            .all()
        )
    if not runs:
        click.echo("(no runs)")
        return
    for r in runs:
        click.echo(
            f"#{r.id:<4} {r.strategy:<24} {r.sport:<6} "
            f"bets={r.bets_placed:<4} roi={r.roi or 0:6.2f}%  "
            f"brier={r.brier_score or 0:.4f}  "
            f"dd={(r.max_drawdown or 0):.3f}"
        )


@cli.group("data")
def data_group() -> None:
    """Ingest real historical data (NBA game results + odds CSVs)."""


@data_group.command("ingest-games")
@click.option("--season", required=True, help="NBA season like '2023-24'.")
def data_ingest_games_cmd(season: str) -> None:
    """Pull completed regular-season games from nba_api into historical_games."""
    # Lazy import so the CLI still loads if the `ml` extras aren't installed.
    from betedge.ml.data import db_season_key, ingest_nba_games

    with SessionLocal() as session:
        result = ingest_nba_games(session, season)
    click.echo(
        json.dumps(
            {
                "season": db_season_key(season),
                "games_inserted": result.games_inserted,
                "games_skipped": result.games_skipped,
            },
            indent=2,
        )
    )


@data_group.command("ingest-odds")
@click.option("--season", required=True, help="Season to attach odds to, e.g. '2023-24'.")
@click.option(
    "--path",
    "csv_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="CSV with columns: date, home_team, away_team, home_ml, away_ml, [book].",
)
@click.option("--market", default="h2h", show_default=True)
def data_ingest_odds_cmd(season: str, csv_path: Path, market: str) -> None:
    """Attach historical moneylines from a user-supplied CSV to ingested games."""
    from betedge.ml.data import ingest_odds_csv

    with SessionLocal() as session:
        result = ingest_odds_csv(session, csv_path, season=season, market=market)
    click.echo(
        json.dumps(
            {
                "odds_inserted": result.odds_inserted,
                "odds_skipped": result.odds_skipped,
                "odds_unmatched": result.odds_unmatched,
            },
            indent=2,
        )
    )


@data_group.command("ingest-sbr")
@click.option("--season", required=True, help="Season matching the XLSX, e.g. '2023-24'.")
@click.option(
    "--path",
    "xlsx_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="SBR NBA season .xlsx (download from sportsbookreviewsonline.com).",
)
@click.option("--book", default="consensus", show_default=True)
def data_ingest_sbr_cmd(season: str, xlsx_path: Path, book: str) -> None:
    """Attach SBR moneylines to ingested games, cross-checking scores vs nba_api."""
    from betedge.ml.sbr import ingest_sbr_odds

    with SessionLocal() as session:
        result = ingest_sbr_odds(session, xlsx_path, season=season, book=book)
    click.echo(
        json.dumps(
            {
                "odds_inserted": result.odds_inserted,
                "odds_skipped": result.odds_skipped,
                "odds_unmatched": result.odds_unmatched,
                "games_score_mismatched": result.games_score_mismatched,
            },
            indent=2,
        )
    )


@data_group.command("verify")
@click.option("--season", required=True, help="Season to verify, e.g. '2023-24'.")
def data_verify_cmd(season: str) -> None:
    """Print coverage + integrity stats for an ingested season."""
    from sqlalchemy import func, select

    from betedge.ml.data import db_season_key
    from betedge.models import HistoricalGame, HistoricalOdds

    db_season = db_season_key(season)
    with SessionLocal() as session:
        game_count = session.scalar(
            select(func.count(HistoricalGame.id)).where(
                HistoricalGame.sport == "NBA",
                HistoricalGame.season == db_season,
            )
        ) or 0
        book_stats = session.execute(
            select(HistoricalOdds.book, func.count(HistoricalOdds.id))
            .join(HistoricalGame)
            .where(
                HistoricalGame.sport == "NBA",
                HistoricalGame.season == db_season,
            )
            .group_by(HistoricalOdds.book)
        ).all()
        games_with_odds = session.scalar(
            select(func.count(func.distinct(HistoricalOdds.game_id)))
            .join(HistoricalGame)
            .where(
                HistoricalGame.sport == "NBA",
                HistoricalGame.season == db_season,
            )
        ) or 0

    click.echo(
        json.dumps(
            {
                "season": db_season,
                "games": game_count,
                "games_with_any_odds": games_with_odds,
                "odds_coverage_percent": (
                    round(100 * games_with_odds / game_count, 1) if game_count else 0.0
                ),
                "odds_rows_by_book": {book: count for book, count in book_stats},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    cli()
