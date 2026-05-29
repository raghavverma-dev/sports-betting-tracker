"""Tests for leakage-safe pre-game feature engineering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from betedge.ml.features import FEATURE_COLUMNS, build_feature_rows
from betedge.models import HistoricalGame


def _game(
    gid: int,
    day_offset: int,
    home: str,
    away: str,
    home_score: int,
    away_score: int,
    season: str = "2023-24-real",
) -> HistoricalGame:
    return HistoricalGame(
        id=gid,
        external_id=f"t-{gid}",
        sport="NBA",
        season=season,
        commence_time=datetime(2023, 10, 24, 19, tzinfo=UTC) + timedelta(days=day_offset),
        home_team=home,
        away_team=away,
        home_score=home_score,
        away_score=away_score,
        winner="home" if home_score > away_score else "away",
    )


def test_first_game_uses_neutral_priors() -> None:
    rows = build_feature_rows([_game(1, 0, "A", "B", 110, 100)])
    assert len(rows) == 1
    f = rows[0].features
    # No prior history -> 0.5 win priors, 0 margin, max rest, 0 games played.
    assert f["home_rolling_winpct"] == 0.5
    assert f["away_rolling_winpct"] == 0.5
    assert f["home_rolling_margin"] == 0.0
    assert f["home_season_winpct"] == 0.5
    assert f["home_games_played"] == 0.0
    assert f["away_games_played"] == 0.0


def test_feature_row_never_sees_its_own_result() -> None:
    # Team A wins game 1 big; in game 2 (A home again) the features must
    # reflect ONLY game 1, never game 2's own outcome.
    games = [
        _game(1, 0, "A", "B", 120, 100),  # A +20
        _game(2, 2, "A", "C", 90, 110),  # A loses, but features predate this
    ]
    rows = build_feature_rows(games)
    g2 = next(r for r in rows if r.game_id == 2)
    # After exactly one prior win, A's rolling win% is 1.0 and margin +20 —
    # if game 2's own loss leaked in, these would differ.
    assert g2.features["home_rolling_winpct"] == 1.0
    assert g2.features["home_rolling_margin"] == 20.0
    assert g2.features["home_season_winpct"] == 1.0
    assert g2.features["home_games_played"] == 1.0


def test_rest_days_tracks_prior_game() -> None:
    games = [
        _game(1, 0, "A", "B", 110, 100),
        _game(2, 3, "A", "C", 105, 100),  # A plays again 3 days later
    ]
    rows = build_feature_rows(games)
    g2 = next(r for r in rows if r.game_id == 2)
    assert g2.features["home_rest_days"] == 3.0


def test_season_boundary_resets_state() -> None:
    games = [
        _game(1, 0, "A", "B", 120, 100, season="2022-23-real"),
        _game(2, 400, "A", "C", 100, 110, season="2023-24-real"),
    ]
    rows = build_feature_rows(games)
    g2 = next(r for r in rows if r.game_id == 2)
    # New season -> A's prior-season win history must not carry over.
    assert g2.features["home_rolling_winpct"] == 0.5
    assert g2.features["home_games_played"] == 0.0


def test_vector_matches_feature_columns_order() -> None:
    rows = build_feature_rows([_game(1, 0, "A", "B", 110, 100)])
    vec = rows[0].vector()
    assert len(vec) == len(FEATURE_COLUMNS)
    assert vec == [rows[0].features[c] for c in FEATURE_COLUMNS]


def test_elo_starts_neutral_and_reflects_only_prior_games() -> None:
    games = [
        _game(1, 0, "A", "B", 120, 100),  # A beats B
        _game(2, 2, "A", "C", 90, 110),  # A loses to C (must not leak back)
    ]
    rows = build_feature_rows(games)
    g1 = next(r for r in rows if r.game_id == 1)
    g2 = next(r for r in rows if r.game_id == 2)
    # First game: both teams at the 1500 base, so the only edge is home court.
    assert g1.features["home_elo"] == 1500.0
    assert g1.features["away_elo"] == 1500.0
    assert g1.features["elo_diff"] == 100.0  # pure home-court bump
    # Game 2's home_elo must reflect ONLY game 1's win (A gained points),
    # never game 2's own loss.
    assert g2.features["home_elo"] > 1500.0


def test_elo_regresses_toward_mean_across_seasons() -> None:
    # A dominates season 1, then opens season 2. Its season-2 opening Elo
    # should be elevated (strength carries) but pulled back toward 1500.
    s1 = [
        _game(i, i, "A", f"X{i}", 130, 100, season="2021-22-real")
        for i in range(1, 6)
    ]
    opener = _game(99, 400, "A", "Y", 100, 110, season="2022-23-real")
    rows = build_feature_rows([*s1, opener])
    end_s1 = max(
        r.features["home_elo"] for r in rows if r.game_id in {g.id for g in s1}
    )
    start_s2 = next(r for r in rows if r.game_id == 99).features["home_elo"]
    assert start_s2 < end_s1  # regressed downward
    assert start_s2 > 1500.0  # but still above league average


def test_back_to_back_flag() -> None:
    games = [
        _game(1, 0, "A", "B", 110, 100),
        _game(2, 1, "A", "C", 105, 100),  # A plays the very next day
        _game(3, 4, "A", "D", 105, 100),  # A rests 3 days
    ]
    rows = build_feature_rows(games)
    assert next(r for r in rows if r.game_id == 1).features["home_b2b"] == 0.0
    assert next(r for r in rows if r.game_id == 2).features["home_b2b"] == 1.0
    assert next(r for r in rows if r.game_id == 3).features["home_b2b"] == 0.0


def test_rest_advantage_is_signed_difference() -> None:
    games = [
        _game(1, 0, "A", "B", 110, 100),  # A's prior game
        _game(2, 0, "C", "D", 110, 100),  # C's prior game (same day)
        _game(3, 2, "A", "C", 105, 100),  # A rests 2, C rests 2 -> 0 advantage
    ]
    rows = build_feature_rows(games)
    g3 = next(r for r in rows if r.game_id == 3)
    assert g3.features["rest_advantage"] == (
        g3.features["home_rest_days"] - g3.features["away_rest_days"]
    )
