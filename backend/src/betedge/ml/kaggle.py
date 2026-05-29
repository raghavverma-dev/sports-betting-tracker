"""Kaggle NBA betting-data ingestion.

Loads the public ``cviaxmiwnptr/nba-betting-data-october-2007-to-june-2024``
dataset (file ``nba_2008-2025.csv``, CC0-licensed). Unlike the nba_api +
SBR two-step path in ``data.py`` / ``sbr.py``, this dataset ships game
results *and* closing moneylines in one wide CSV, so a single pass
populates both ``historical_games`` and ``historical_odds`` — no network
calls, fully reproducible offline.

CSV schema (one row per game):
    season,date,regular,playoffs,away,home,score_away,score_home,
    ...,moneyline_away,moneyline_home,...

``season`` is the season's *end* year (e.g. ``2024`` = the 2023-24
season, whose opener is dated 2023-10). Team columns are lowercase
abbreviations (``por``, ``sa``, ``gs``). Rows are tagged
``season="<YYYY-YY>-real"`` so they never collide with synthetic data.

Idempotent: re-running skips games already present (by ``external_id``)
and odds already present (by the composite unique key).
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from betedge.ml.data import IngestResult, normalize_team
from betedge.models import HistoricalGame, HistoricalOdds

logger = logging.getLogger(__name__)

# Abbreviations this dataset uses that `data.normalize_team` doesn't cover.
# Everything else (por, sa, gs, lac, lal, no, ny, phx, ...) is already in
# the general alias map.
_KAGGLE_TEAM_FIXUPS: dict[str, str] = {
    "bkn": "Brooklyn Nets",
    "wsh": "Washington Wizards",
    "utah": "Utah Jazz",
}

_REQUIRED_COLUMNS = frozenset(
    {
        "season",
        "date",
        "regular",
        "away",
        "home",
        "score_away",
        "score_home",
        "moneyline_away",
        "moneyline_home",
    }
)


def season_end_year_to_label(end_year: int) -> str:
    """``2024`` -> ``2023-24`` (the season-string this dataset's year means)."""
    start = end_year - 1
    return f"{start}-{end_year % 100:02d}"


def _norm_team(raw: str | None) -> str | None:
    if raw is None:
        return None
    key = raw.strip().lower()
    if key in _KAGGLE_TEAM_FIXUPS:
        return _KAGGLE_TEAM_FIXUPS[key]
    return normalize_team(raw)


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    s = str(value).replace("+", "").strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None
    # Day-granularity source; anchor at 19:00 UTC for stable time ordering
    # (matches the nba_api ingester in data.py).
    return datetime.combine(d, time(hour=19), tzinfo=UTC)


def _is_truthy(value: str | None) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes", "t")


@dataclass(frozen=True, slots=True)
class _Row:
    commence: datetime
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    home_ml: int
    away_ml: int


def _read_rows(
    path: Path,
    *,
    season_label: str,
    regular_season_only: bool,
) -> list[_Row]:
    target_end_year = int(season_label.split("-", 1)[0]) + 1
    out: list[_Row] = []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: no header row")
        missing = _REQUIRED_COLUMNS - {h.strip() for h in reader.fieldnames}
        if missing:
            raise ValueError(f"{path}: missing required columns: {sorted(missing)}")

        for line_no, raw in enumerate(reader, start=2):
            if _parse_int(raw["season"]) != target_end_year:
                continue
            if regular_season_only and not _is_truthy(raw["regular"]):
                continue

            commence = _parse_date(raw["date"])
            home = _norm_team(raw["home"])
            away = _norm_team(raw["away"])
            home_score = _parse_int(raw["score_home"])
            away_score = _parse_int(raw["score_away"])
            home_ml = _parse_int(raw["moneyline_home"])
            away_ml = _parse_int(raw["moneyline_away"])

            if None in (commence, home, away, home_score, away_score, home_ml, away_ml):
                logger.warning("kaggle csv %s line %d: skipped (unparseable)", path.name, line_no)
                continue

            out.append(
                _Row(
                    commence=commence,  # type: ignore[arg-type]
                    home_team=home,  # type: ignore[arg-type]
                    away_team=away,  # type: ignore[arg-type]
                    home_score=home_score,  # type: ignore[arg-type]
                    away_score=away_score,  # type: ignore[arg-type]
                    home_ml=home_ml,  # type: ignore[arg-type]
                    away_ml=away_ml,  # type: ignore[arg-type]
                )
            )
    return out


def ingest_kaggle_csv(
    session: Session,
    path: Path,
    *,
    season: str,
    book: str = "consensus",
    market: str = "h2h",
    regular_season_only: bool = True,
) -> IngestResult:
    """Ingest games + closing moneylines for one season from the Kaggle CSV.

    ``season`` is a label like ``2023-24``; only rows whose dataset
    ``season`` end-year matches are loaded. Games are keyed by
    ``external_id = "kaggle-<season>-<away>-<home>-<YYYYMMDD>"`` for
    idempotency. Returns counts for inserted/skipped games and odds.
    """
    rows = _read_rows(path, season_label=season, regular_season_only=regular_season_only)
    db_season = f"{season}-real"

    existing_ext_ids = set(
        session.scalars(
            select(HistoricalGame.external_id).where(HistoricalGame.season == db_season)
        ).all()
    )
    existing_odds_keys: set[tuple[int, str, str, str]] = {
        tuple(r)
        for r in session.execute(
            select(
                HistoricalOdds.game_id,
                HistoricalOdds.book,
                HistoricalOdds.market,
                HistoricalOdds.outcome,
            )
            .join(HistoricalGame)
            .where(HistoricalGame.season == db_season)
        ).all()
    }

    games_inserted = games_skipped = odds_inserted = odds_skipped = 0

    for row in rows:
        ext_id = (
            f"kaggle-{season}-{row.away_team}-{row.home_team}"
            f"-{row.commence.strftime('%Y%m%d')}"
        ).replace(" ", "_")

        game = session.scalar(
            select(HistoricalGame).where(HistoricalGame.external_id == ext_id)
        )
        if game is None:
            game = HistoricalGame(
                external_id=ext_id,
                sport="NBA",
                season=db_season,
                commence_time=row.commence,
                home_team=row.home_team,
                away_team=row.away_team,
                home_score=row.home_score,
                away_score=row.away_score,
                winner="home" if row.home_score > row.away_score else "away",
            )
            session.add(game)
            session.flush()  # assign game.id
            existing_ext_ids.add(ext_id)
            games_inserted += 1
        else:
            games_skipped += 1

        for outcome, ml in ((row.home_team, row.home_ml), (row.away_team, row.away_ml)):
            key = (game.id, book, market, outcome)
            if key in existing_odds_keys:
                odds_skipped += 1
                continue
            session.add(
                HistoricalOdds(
                    game_id=game.id,
                    book=book,
                    market=market,
                    outcome=outcome,
                    american_odds=ml,
                )
            )
            existing_odds_keys.add(key)
            odds_inserted += 1

    session.commit()
    return IngestResult(
        games_inserted=games_inserted,
        games_skipped=games_skipped,
        odds_inserted=odds_inserted,
        odds_skipped=odds_skipped,
    )
