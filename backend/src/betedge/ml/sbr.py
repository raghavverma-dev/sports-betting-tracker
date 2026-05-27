"""SportsBookReviewsOnline (SBR) historical NBA odds loader.

SBR publishes one ``.xlsx`` per season at
``sportsbookreviewsonline.com/scoresoddsarchives/nba``. The file must
be downloaded manually (their URL pattern changes between seasons and
automated scraping is gray). The file is then parsed here.

**Layout of an SBR NBA season file:**

Columns: ``Date | Rot | VH | Team | 1st | 2nd | 3rd | 4th | Final | Open | Close | ML | 2H``

Two rows per game — first the visitor (``VH == "V"``), then the home
team (``VH == "H"``). ``Date`` is MMDD (``1025`` = Oct 25); the season
year is inferred from the season string we're ingesting for.

**Why we cross-check:** SBR is the standard open dataset for US
closing lines but it's human-entered — occasional typos happen. We
join every SBR row against ``historical_games`` (populated from the
authoritative ``nba_api`` feed) and assert that both the date and the
final score match. Mismatches are logged and skipped, not silently
trusted. The ``IngestResult.odds_unmatched`` counter surfaces them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from betedge.ml.data import IngestResult, db_season_key, normalize_team
from betedge.models import HistoricalGame, HistoricalOdds

logger = logging.getLogger(__name__)


# SBR writes compound team names without spaces (``LALakers``,
# ``GoldenState``). Map those to nba_api's canonical form.
_SBR_TEAM_MAP: dict[str, str] = {
    "atlanta": "Atlanta Hawks",
    "boston": "Boston Celtics",
    "brooklyn": "Brooklyn Nets",
    "charlotte": "Charlotte Hornets",
    "chicago": "Chicago Bulls",
    "cleveland": "Cleveland Cavaliers",
    "dallas": "Dallas Mavericks",
    "denver": "Denver Nuggets",
    "detroit": "Detroit Pistons",
    "goldenstate": "Golden State Warriors",
    "houston": "Houston Rockets",
    "indiana": "Indiana Pacers",
    "laclippers": "Los Angeles Clippers",
    "lalakers": "Los Angeles Lakers",
    "memphis": "Memphis Grizzlies",
    "miami": "Miami Heat",
    "milwaukee": "Milwaukee Bucks",
    "minnesota": "Minnesota Timberwolves",
    "neworleans": "New Orleans Pelicans",
    "newyork": "New York Knicks",
    "oklahomacity": "Oklahoma City Thunder",
    "orlando": "Orlando Magic",
    "philadelphia": "Philadelphia 76ers",
    "phoenix": "Phoenix Suns",
    "portland": "Portland Trail Blazers",
    "sacramento": "Sacramento Kings",
    "sanantonio": "San Antonio Spurs",
    "toronto": "Toronto Raptors",
    "utah": "Utah Jazz",
    "washington": "Washington Wizards",
}


def _normalize_sbr_team(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.strip().lower().replace(" ", "")
    if key in _SBR_TEAM_MAP:
        return _SBR_TEAM_MAP[key]
    return normalize_team(raw)  # Fall through to the general normalizer.


@dataclass(frozen=True, slots=True)
class ParsedSbrGame:
    day: date
    home_team: str
    away_team: str
    home_final: int
    away_final: int
    home_ml: int
    away_ml: int


def _parse_mmdd_to_date(raw: Any, season: str) -> date | None:
    """Turn SBR's 3- or 4-digit MMDD value into a full date.

    The season anchors the year: months Oct–Dec fall in season's start
    year, Jan–Sep in start year + 1.
    """
    if raw is None:
        return None
    s = str(raw).strip().split(".")[0].zfill(4)
    if len(s) != 4 or not s.isdigit():
        return None
    month, day_ = int(s[:2]), int(s[2:])
    if not (1 <= month <= 12 and 1 <= day_ <= 31):
        return None
    try:
        start_year = int(season.split("-", 1)[0])
    except (ValueError, IndexError):
        return None
    year = start_year if month >= 10 else start_year + 1
    try:
        return date(year, month, day_)
    except ValueError:
        return None


def _parse_ml(v: Any) -> int | None:
    """SBR ML cells can be ints, floats, ``"+130"``, or ``"NL"`` (no line)."""
    if v is None:
        return None
    if isinstance(v, int | float):
        return int(v)
    if isinstance(v, str):
        s = v.strip().replace("+", "")
        if not s or s.upper() in ("NL", "PK", "N/A", "-"):
            return None
        try:
            return int(s)
        except ValueError:
            return None
    return None


def _parse_final(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_sbr_rows(rows: list[dict[str, Any]], season: str) -> list[ParsedSbrGame]:
    """Collapse SBR's two-rows-per-game schema into one ``ParsedSbrGame`` each.

    Pure (no I/O) so it can be unit-tested without an XLSX file.
    """
    out: list[ParsedSbrGame] = []
    i, n = 0, len(rows)
    while i < n - 1:
        r_v, r_h = rows[i], rows[i + 1]
        if str(r_v.get("VH", "")).strip().upper() != "V" or \
                str(r_h.get("VH", "")).strip().upper() != "H":
            i += 1  # Unpaired row; try to resync on the next line.
            continue

        day = _parse_mmdd_to_date(r_v.get("Date"), season)
        away = _normalize_sbr_team(str(r_v.get("Team", "")))
        home = _normalize_sbr_team(str(r_h.get("Team", "")))
        away_final = _parse_final(r_v.get("Final"))
        home_final = _parse_final(r_h.get("Final"))
        away_ml = _parse_ml(r_v.get("ML"))
        home_ml = _parse_ml(r_h.get("ML"))

        if all(x is not None for x in (day, away, home, away_final, home_final, away_ml, home_ml)):
            out.append(
                ParsedSbrGame(
                    day=day,  # type: ignore[arg-type]
                    home_team=home,  # type: ignore[arg-type]
                    away_team=away,  # type: ignore[arg-type]
                    home_final=home_final,  # type: ignore[arg-type]
                    away_final=away_final,  # type: ignore[arg-type]
                    home_ml=home_ml,  # type: ignore[arg-type]
                    away_ml=away_ml,  # type: ignore[arg-type]
                )
            )
        i += 2
    return out


def load_sbr_xlsx(path: Path) -> list[dict[str, Any]]:
    """Read an SBR season XLSX into header-keyed dict rows."""
    try:
        import openpyxl  # type: ignore[import-untyped]
    except ImportError as e:
        raise RuntimeError(
            "openpyxl is required. Install the 'ml' extras: pip install -e '.[ml]'"
        ) from e

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = wb.active
    if sheet is None:
        raise ValueError(f"{path}: workbook has no active sheet")

    rows_iter = sheet.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration as e:
        raise ValueError(f"{path}: empty sheet") from e
    header = [str(v).strip() if v is not None else "" for v in header_row]

    rows: list[dict[str, Any]] = []
    for row in rows_iter:
        if all(v is None for v in row):
            continue
        rows.append(dict(zip(header, row, strict=False)))
    return rows


@dataclass(frozen=True, slots=True)
class SbrIngestResult(IngestResult):
    games_score_mismatched: int = 0


def ingest_sbr_odds(
    session: Session,
    path: Path,
    *,
    season: str,
    book: str = "consensus",
    market: str = "h2h",
) -> SbrIngestResult:
    """Attach SBR moneylines to already-ingested ``historical_games``.

    Preconditions: run ``ingest_nba_games`` for the same season first,
    so we have authoritative game records to validate against.

    Side effects: for each SBR game, cross-checks the final score
    against the DB row. Mismatches are logged and the odds are NOT
    written — we refuse to pollute the DB with rows whose source
    disagrees with itself.
    """
    parsed = parse_sbr_rows(load_sbr_xlsx(path), season)
    db_season = db_season_key(season)

    games = session.scalars(
        select(HistoricalGame).where(
            HistoricalGame.sport == "NBA",
            HistoricalGame.season == db_season,
        )
    ).all()
    games_by_key: dict[tuple[date, str, str], HistoricalGame] = {
        (g.commence_time.date(), g.home_team, g.away_team): g for g in games
    }

    existing_odds_keys: set[tuple[int, str, str, str]] = {
        tuple(row)
        for row in session.execute(
            select(
                HistoricalOdds.game_id,
                HistoricalOdds.book,
                HistoricalOdds.market,
                HistoricalOdds.outcome,
            ).join(HistoricalGame).where(
                HistoricalGame.sport == "NBA",
                HistoricalGame.season == db_season,
            )
        ).all()
    }

    inserted = skipped = unmatched = mismatched = 0
    for p in parsed:
        game = games_by_key.get((p.day, p.home_team, p.away_team))
        if game is None:
            unmatched += 1
            continue
        if game.home_score != p.home_final or game.away_score != p.away_final:
            logger.warning(
                "SBR/nba_api score mismatch on %s %s@%s: nba=%d-%d sbr=%d-%d — skipping odds",
                p.day, p.away_team, p.home_team,
                game.home_score, game.away_score, p.home_final, p.away_final,
            )
            mismatched += 1
            continue

        for outcome, ml in ((game.home_team, p.home_ml), (game.away_team, p.away_ml)):
            key = (game.id, book, market, outcome)
            if key in existing_odds_keys:
                skipped += 1
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
            inserted += 1

    session.commit()
    return SbrIngestResult(
        odds_inserted=inserted,
        odds_skipped=skipped,
        odds_unmatched=unmatched,
        games_score_mismatched=mismatched,
    )


# Re-exported for callers that want to inspect IngestResult with the
# SBR-specific ``games_score_mismatched`` field without importing it
# directly from this module.
__all__ = [
    "ParsedSbrGame",
    "SbrIngestResult",
    "ingest_sbr_odds",
    "load_sbr_xlsx",
    "parse_sbr_rows",
    "replace",
]
