"""Tests for SBR parser and ingest with cross-check."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from betedge.ml.data import ingest_nba_games
from betedge.ml.sbr import (
    ParsedSbrGame,
    _normalize_sbr_team,
    _parse_mmdd_to_date,
    ingest_sbr_odds,
    parse_sbr_rows,
)
from betedge.models import HistoricalOdds


def _fake_nba_rows() -> list[dict[str, object]]:
    """Mirror of the fixture in test_ml_data — 2 games on 2023-10-24."""
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


def _sbr_rows(games: list[dict[str, object]]) -> list[dict[str, object]]:
    """Return SBR-shaped rows for a list of game dicts (pre-parse)."""
    out: list[dict[str, object]] = []
    for g in games:
        out.append({
            "Date": g["Date"], "VH": "V", "Team": g["Away"],
            "Final": g["AwayPts"], "ML": g["AwayML"],
        })
        out.append({
            "Date": g["Date"], "VH": "H", "Team": g["Home"],
            "Final": g["HomePts"], "ML": g["HomeML"],
        })
    return out


def test_parse_mmdd_to_date_handles_year_boundary() -> None:
    assert _parse_mmdd_to_date(1025, "2023-24") == date(2023, 10, 25)
    assert _parse_mmdd_to_date(325, "2023-24") == date(2024, 3, 25)
    assert _parse_mmdd_to_date("0325", "2023-24") == date(2024, 3, 25)
    assert _parse_mmdd_to_date(1232, "2023-24") is None
    assert _parse_mmdd_to_date(None, "2023-24") is None


def test_normalize_sbr_team_compound_names() -> None:
    assert _normalize_sbr_team("LALakers") == "Los Angeles Lakers"
    assert _normalize_sbr_team("GoldenState") == "Golden State Warriors"
    assert _normalize_sbr_team("LAClippers") == "Los Angeles Clippers"
    assert _normalize_sbr_team("OklahomaCity") == "Oklahoma City Thunder"
    assert _normalize_sbr_team("Denver") == "Denver Nuggets"
    assert _normalize_sbr_team("Boston Celtics") == "Boston Celtics"


def test_parse_sbr_rows_collapses_v_then_h_pairs() -> None:
    rows = _sbr_rows([
        {"Date": 1024, "Away": "LALakers", "AwayPts": 107, "AwayML": 155,
         "Home": "Denver", "HomePts": 119, "HomeML": -180},
        {"Date": 1024, "Away": "GoldenState", "AwayPts": 104, "AwayML": 100,
         "Home": "Phoenix", "HomePts": 108, "HomeML": -120},
    ])
    games = parse_sbr_rows(rows, "2023-24")
    assert len(games) == 2

    g1 = games[0]
    assert g1 == ParsedSbrGame(
        day=date(2023, 10, 24),
        home_team="Denver Nuggets", away_team="Los Angeles Lakers",
        home_final=119, away_final=107, home_ml=-180, away_ml=155,
    )


def test_parse_sbr_rows_skips_rows_with_no_line() -> None:
    rows = _sbr_rows([
        {"Date": 1024, "Away": "LALakers", "AwayPts": 107, "AwayML": "NL",
         "Home": "Denver", "HomePts": 119, "HomeML": -180},
    ])
    assert parse_sbr_rows(rows, "2023-24") == []


def test_ingest_sbr_odds_matches_and_writes(session: Session, tmp_path: Path) -> None:
    ingest_nba_games(session, "2023-24", fetch_fn=lambda _s: _fake_nba_rows())

    sbr_rows = _sbr_rows([
        {"Date": 1024, "Away": "LALakers", "AwayPts": 107, "AwayML": 155,
         "Home": "Denver", "HomePts": 119, "HomeML": -180},
        {"Date": 1024, "Away": "GoldenState", "AwayPts": 104, "AwayML": 100,
         "Home": "Phoenix", "HomePts": 108, "HomeML": -120},
    ])

    with patch("betedge.ml.sbr.load_sbr_xlsx", return_value=sbr_rows):
        result = ingest_sbr_odds(session, tmp_path / "fake.xlsx", season="2023-24")

    assert result.odds_inserted == 4  # 2 games × 2 sides
    assert result.games_score_mismatched == 0
    assert result.odds_unmatched == 0

    rows = session.query(HistoricalOdds).all()
    assert {r.book for r in rows} == {"consensus"}
    den = next(r for r in rows if r.outcome == "Denver Nuggets")
    assert den.american_odds == -180


def test_ingest_sbr_odds_refuses_score_mismatch(session: Session, tmp_path: Path) -> None:
    """If SBR's final score disagrees with nba_api's, skip the row."""
    ingest_nba_games(session, "2023-24", fetch_fn=lambda _s: _fake_nba_rows())

    bad_rows = _sbr_rows([
        {"Date": 1024, "Away": "LALakers", "AwayPts": 108, "AwayML": 155,
         "Home": "Denver", "HomePts": 120, "HomeML": -180},
    ])
    with patch("betedge.ml.sbr.load_sbr_xlsx", return_value=bad_rows):
        result = ingest_sbr_odds(session, tmp_path / "fake.xlsx", season="2023-24")

    assert result.games_score_mismatched == 1
    assert result.odds_inserted == 0
    assert session.query(HistoricalOdds).count() == 0


def test_ingest_sbr_odds_reports_unmatched(session: Session, tmp_path: Path) -> None:
    ingest_nba_games(session, "2023-24", fetch_fn=lambda _s: _fake_nba_rows())

    rows = _sbr_rows([
        {"Date": 1130, "Away": "LALakers", "AwayPts": 99, "AwayML": 140,
         "Home": "Denver", "HomePts": 110, "HomeML": -160},
    ])
    with patch("betedge.ml.sbr.load_sbr_xlsx", return_value=rows):
        result = ingest_sbr_odds(session, tmp_path / "fake.xlsx", season="2023-24")

    assert result.odds_unmatched == 1
    assert result.odds_inserted == 0


def test_ingest_sbr_odds_idempotent(session: Session, tmp_path: Path) -> None:
    ingest_nba_games(session, "2023-24", fetch_fn=lambda _s: _fake_nba_rows())
    rows = _sbr_rows([
        {"Date": 1024, "Away": "LALakers", "AwayPts": 107, "AwayML": 155,
         "Home": "Denver", "HomePts": 119, "HomeML": -180},
    ])
    with patch("betedge.ml.sbr.load_sbr_xlsx", return_value=rows):
        first = ingest_sbr_odds(session, tmp_path / "f.xlsx", season="2023-24")
        second = ingest_sbr_odds(session, tmp_path / "f.xlsx", season="2023-24")
    assert first.odds_inserted == 2
    assert second.odds_inserted == 0
    assert second.odds_skipped == 2


def test_parse_sbr_rows_resyncs_on_unpaired_row() -> None:
    rows = [
        {"Date": 1024, "VH": "V", "Team": "Stray", "Final": 100, "ML": 100},
        {"Date": 1024, "VH": "V", "Team": "LALakers", "Final": 107, "ML": 155},
        {"Date": 1024, "VH": "H", "Team": "Denver", "Final": 119, "ML": -180},
    ]
    games = parse_sbr_rows(rows, "2023-24")
    assert len(games) == 1
    assert games[0].home_team == "Denver Nuggets"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+130", 130), ("-150", -150), (130, 130), (-150.0, -150),
        ("NL", None), ("", None), (None, None),
    ],
)
def test_parse_ml_variants(raw: object, expected: int | None) -> None:
    from betedge.ml.sbr import _parse_ml

    assert _parse_ml(raw) == expected
