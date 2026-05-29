"""Tests for betedge.ml.kaggle ingestion (network-free, tmp_path CSV)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from betedge.ml.kaggle import ingest_kaggle_csv, season_end_year_to_label
from betedge.models import HistoricalGame, HistoricalOdds

_HEADER = (
    "season,date,regular,playoffs,away,home,score_away,score_home,"
    "moneyline_away,moneyline_home\n"
)


def _csv(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "nba.csv"
    p.write_text(_HEADER + body, encoding="utf-8")
    return p


def test_season_end_year_to_label() -> None:
    assert season_end_year_to_label(2024) == "2023-24"
    assert season_end_year_to_label(2008) == "2007-08"
    assert season_end_year_to_label(2010) == "2009-10"


def test_ingest_inserts_games_and_odds(session: Session, tmp_path: Path) -> None:
    csv = _csv(
        tmp_path,
        "2024,2023-10-24,True,False,lal,den,107,119,155,-180\n"
        "2024,2023-10-25,True,False,gs,phx,104,108,100,-120\n",
    )
    result = ingest_kaggle_csv(session, csv, season="2023-24")
    assert result.games_inserted == 2
    assert result.odds_inserted == 4  # 2 games x 2 sides

    game = session.query(HistoricalGame).filter_by(home_team="Denver Nuggets").one()
    assert game.away_team == "Los Angeles Lakers"
    assert game.home_score == 119
    assert game.winner == "home"
    assert game.season == "2023-24-real"

    den_ml = (
        session.query(HistoricalOdds)
        .filter_by(outcome="Denver Nuggets", market="h2h")
        .one()
    )
    assert den_ml.american_odds == -180
    assert den_ml.book == "consensus"


def test_ingest_is_idempotent(session: Session, tmp_path: Path) -> None:
    csv = _csv(tmp_path, "2024,2023-10-24,True,False,lal,den,107,119,155,-180\n")
    ingest_kaggle_csv(session, csv, season="2023-24")
    rerun = ingest_kaggle_csv(session, csv, season="2023-24")
    assert rerun.games_inserted == 0
    assert rerun.games_skipped == 1
    assert rerun.odds_inserted == 0
    assert rerun.odds_skipped == 2


def test_ingest_filters_by_season(session: Session, tmp_path: Path) -> None:
    csv = _csv(
        tmp_path,
        "2024,2023-10-24,True,False,lal,den,107,119,155,-180\n"
        "2023,2022-10-24,True,False,lal,den,100,110,150,-170\n",  # different season
    )
    result = ingest_kaggle_csv(session, csv, season="2023-24")
    assert result.games_inserted == 1


def test_ingest_excludes_playoffs_by_default(session: Session, tmp_path: Path) -> None:
    csv = _csv(
        tmp_path,
        "2024,2023-10-24,True,False,lal,den,107,119,155,-180\n"
        "2024,2024-05-01,False,True,bos,mia,98,101,120,-140\n",  # playoff row
    )
    default = ingest_kaggle_csv(session, csv, season="2023-24")
    assert default.games_inserted == 1


def test_ingest_includes_playoffs_when_flagged(session: Session, tmp_path: Path) -> None:
    csv = _csv(
        tmp_path,
        "2024,2024-05-01,False,True,bos,mia,98,101,120,-140\n",
    )
    result = ingest_kaggle_csv(session, csv, season="2023-24", regular_season_only=False)
    assert result.games_inserted == 1


def test_ingest_normalizes_dataset_abbreviation_fixups(
    session: Session, tmp_path: Path
) -> None:
    # bkn, wsh, utah are the codes not covered by the general alias map.
    csv = _csv(
        tmp_path,
        "2024,2023-10-24,True,False,bkn,wsh,100,110,140,-160\n"
        "2024,2023-10-25,True,False,utah,bkn,99,101,130,-150\n",
    )
    result = ingest_kaggle_csv(session, csv, season="2023-24")
    assert result.games_inserted == 2
    teams = {
        t
        for g in session.query(HistoricalGame).all()
        for t in (g.home_team, g.away_team)
    }
    assert {"Brooklyn Nets", "Washington Wizards", "Utah Jazz"} <= teams


def test_ingest_missing_columns_errors(session: Session, tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("season,date,home,away\n2024,2023-10-24,den,lal\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        ingest_kaggle_csv(session, bad, season="2023-24")
