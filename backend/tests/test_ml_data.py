"""Tests for betedge.ml.data ingestion.

Network-free: ``ingest_nba_games`` is tested via its ``fetch_fn`` seam,
and ``ingest_odds_csv`` runs against a tmp_path CSV.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from betedge.ml.data import (
    db_season_key,
    ingest_nba_games,
    ingest_odds_csv,
    normalize_team,
)
from betedge.models import HistoricalGame, HistoricalOdds


def _fake_nba_rows() -> list[dict[str, object]]:
    """Two games, each appearing as two team-rows (as nba_api returns)."""
    return [
        {
            "GAME_ID": "0022300001", "GAME_DATE": "2023-10-24",
            "TEAM_NAME": "Denver Nuggets", "MATCHUP": "DEN vs. LAL",
            "PTS": 119, "WL": "W",
        },
        {
            "GAME_ID": "0022300001", "GAME_DATE": "2023-10-24",
            "TEAM_NAME": "Los Angeles Lakers", "MATCHUP": "LAL @ DEN",
            "PTS": 107, "WL": "L",
        },
        {
            "GAME_ID": "0022300002", "GAME_DATE": "2023-10-24",
            "TEAM_NAME": "Golden State Warriors", "MATCHUP": "GSW @ PHX",
            "PTS": 104, "WL": "L",
        },
        {
            "GAME_ID": "0022300002", "GAME_DATE": "2023-10-24",
            "TEAM_NAME": "Phoenix Suns", "MATCHUP": "PHX vs. GSW",
            "PTS": 108, "WL": "W",
        },
    ]


def test_normalize_team_handles_aliases() -> None:
    assert normalize_team("Boston Celtics") == "Boston Celtics"
    assert normalize_team("bos") == "Boston Celtics"
    assert normalize_team("Celtics") == "Boston Celtics"
    assert normalize_team("  WARRIORS ") == "Golden State Warriors"
    assert normalize_team("") is None
    assert normalize_team(None) is None
    assert normalize_team("Toronto FC") is None  # Not NBA.


def test_db_season_key_rejects_bad_input() -> None:
    assert db_season_key("2023-24") == "2023-24-real"
    assert db_season_key("2023-2024") == "2023-24-real"
    with pytest.raises(ValueError):
        db_season_key("2023")
    with pytest.raises(ValueError):
        db_season_key("2023-2025")  # Not consecutive.


def test_ingest_nba_games_inserts_once_and_is_idempotent(session: Session) -> None:
    result = ingest_nba_games(session, "2023-24", fetch_fn=lambda _s: _fake_nba_rows())
    assert result.games_inserted == 2
    assert result.games_skipped == 0

    games = session.query(HistoricalGame).all()
    assert len(games) == 2
    nuggets_game = next(g for g in games if g.home_team == "Denver Nuggets")
    assert nuggets_game.away_team == "Los Angeles Lakers"
    assert nuggets_game.home_score == 119
    assert nuggets_game.away_score == 107
    assert nuggets_game.winner == "home"
    assert nuggets_game.season == "2023-24-real"
    assert nuggets_game.external_id == "nba-0022300001"

    # Second call should be a no-op on already-ingested games.
    again = ingest_nba_games(session, "2023-24", fetch_fn=lambda _s: _fake_nba_rows())
    assert again.games_inserted == 0
    assert again.games_skipped == 2


def test_ingest_odds_csv_matches_and_attaches(session: Session, tmp_path: Path) -> None:
    ingest_nba_games(session, "2023-24", fetch_fn=lambda _s: _fake_nba_rows())

    csv = tmp_path / "odds.csv"
    csv.write_text(
        "date,home_team,away_team,home_ml,away_ml,book\n"
        "2023-10-24,Denver Nuggets,Lakers,-180,+155,DraftKings\n"
        "2023-10-24,DEN,LAL,-175,+150,FanDuel\n"
        "2023-10-24,PHX,GSW,-120,+100,DraftKings\n"
        # Unmatched — wrong date.
        "2023-10-25,Denver Nuggets,Lakers,-200,+170,DraftKings\n",
        encoding="utf-8",
    )

    result = ingest_odds_csv(session, csv, season="2023-24")
    # 3 rows matched × 2 sides each = 6 inserts; 1 unmatched.
    assert result.odds_inserted == 6
    assert result.odds_skipped == 0
    assert result.odds_unmatched == 1

    # Re-running skips (unique constraint), doesn't duplicate.
    rerun = ingest_odds_csv(session, csv, season="2023-24")
    assert rerun.odds_inserted == 0
    assert rerun.odds_skipped == 6

    # Spot-check one row landed with the right book + outcome.
    dk_denver = (
        session.query(HistoricalOdds)
        .filter_by(book="DraftKings", outcome="Denver Nuggets", market="h2h")
        .one()
    )
    assert dk_denver.american_odds == -180


def test_ingest_odds_csv_missing_columns_errors(session: Session, tmp_path: Path) -> None:
    csv = tmp_path / "bad.csv"
    csv.write_text("date,home_team,away_team\n2023-10-24,BOS,NYK\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        ingest_odds_csv(session, csv, season="2023-24")


def test_ingest_odds_csv_defaults_book_to_consensus(
    session: Session, tmp_path: Path
) -> None:
    ingest_nba_games(session, "2023-24", fetch_fn=lambda _s: _fake_nba_rows())
    csv = tmp_path / "odds.csv"
    csv.write_text(
        "date,home_team,away_team,home_ml,away_ml\n"
        "2023-10-24,Denver Nuggets,Lakers,-180,+155\n",
        encoding="utf-8",
    )
    result = ingest_odds_csv(session, csv, season="2023-24")
    assert result.odds_inserted == 2

    rows = session.query(HistoricalOdds).all()
    assert {r.book for r in rows} == {"consensus"}


def test_ingest_nba_games_ignores_partial_pairs(session: Session) -> None:
    """A feed hiccup where one team-row is missing should be skipped, not crash."""
    partial = [
        {
            "GAME_ID": "0022300099", "GAME_DATE": "2023-10-24",
            "TEAM_NAME": "Boston Celtics", "MATCHUP": "BOS vs. MIA",
            "PTS": 110, "WL": "W",
        },
        # MIA row missing
    ]
    result = ingest_nba_games(session, "2023-24", fetch_fn=lambda _s: partial)
    assert result.games_inserted == 0


def test_ingest_nba_games_commence_time_is_utc(session: Session) -> None:
    ingest_nba_games(session, "2023-24", fetch_fn=lambda _s: _fake_nba_rows()[:2])
    game = session.query(HistoricalGame).one()
    # Anchored at 7pm for deterministic ordering. SQLite drops tzinfo on
    # round-trip; Postgres preserves it. Compare the naive-equivalent parts.
    assert game.commence_time.replace(tzinfo=None) == datetime(2023, 10, 24, 19, 0)
    # When Postgres is the backend, tz is preserved and will equal UTC.
    if game.commence_time.tzinfo is not None:
        assert game.commence_time.tzinfo.utcoffset(game.commence_time) == UTC.utcoffset(
            datetime.now()
        )
