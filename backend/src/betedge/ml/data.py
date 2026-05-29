"""Real NBA historical data ingestion.

Two entry points:
  - ``ingest_nba_games(session, season)`` pulls final scores for a season
    via ``nba_api`` (official NBA stats endpoint wrapper).
  - ``ingest_odds_csv(session, path, season=...)`` attaches historical
    moneylines from a user-supplied CSV to already-ingested games.

The split exists because ``nba_api`` provides game results for free but
not closing odds. Odds come from third-party corpora (Kaggle,
sportsbookreviewsonline, etc.) which ship as CSVs. Decoupling lets a
user re-ingest odds without re-hitting the NBA stats endpoint.

Every ingested row is tagged ``season="<input>-real"`` so it never
collides with synthetic data produced by ``backtest/seed.py``.

Both functions are idempotent: re-running skips rows that already
exist (games by ``external_id``, odds by the composite unique key
``(game_id, book, market, outcome)``).
"""

from __future__ import annotations

import csv
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from betedge.models import HistoricalGame, HistoricalOdds

logger = logging.getLogger(__name__)


# Canonical NBA team names as used by nba_api's TEAM_NAME field.
_CANONICAL_TEAMS: tuple[str, ...] = (
    "Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets",
    "Chicago Bulls", "Cleveland Cavaliers", "Dallas Mavericks", "Denver Nuggets",
    "Detroit Pistons", "Golden State Warriors", "Houston Rockets", "Indiana Pacers",
    "Los Angeles Clippers", "Los Angeles Lakers", "Memphis Grizzlies", "Miami Heat",
    "Milwaukee Bucks", "Minnesota Timberwolves", "New Orleans Pelicans", "New York Knicks",
    "Oklahoma City Thunder", "Orlando Magic", "Philadelphia 76ers", "Phoenix Suns",
    "Portland Trail Blazers", "Sacramento Kings", "San Antonio Spurs", "Toronto Raptors",
    "Utah Jazz", "Washington Wizards",
)

# Aliases that odds CSVs commonly use (abbreviations, nicknames, mascot-only).
# Keys are lowercase so lookup is case-insensitive.
_ALIASES: dict[str, str] = {
    **{name.lower(): name for name in _CANONICAL_TEAMS},
    "atl": "Atlanta Hawks", "bos": "Boston Celtics", "bkn": "Brooklyn Nets",
    "brk": "Brooklyn Nets", "cha": "Charlotte Hornets", "cho": "Charlotte Hornets",
    "chi": "Chicago Bulls", "cle": "Cleveland Cavaliers", "dal": "Dallas Mavericks",
    "den": "Denver Nuggets", "det": "Detroit Pistons", "gsw": "Golden State Warriors",
    "gs": "Golden State Warriors", "hou": "Houston Rockets", "ind": "Indiana Pacers",
    "lac": "Los Angeles Clippers", "lal": "Los Angeles Lakers", "mem": "Memphis Grizzlies",
    "mia": "Miami Heat", "mil": "Milwaukee Bucks", "min": "Minnesota Timberwolves",
    "nop": "New Orleans Pelicans", "no": "New Orleans Pelicans", "nyk": "New York Knicks",
    "ny": "New York Knicks", "okc": "Oklahoma City Thunder", "orl": "Orlando Magic",
    "phi": "Philadelphia 76ers", "phx": "Phoenix Suns", "pho": "Phoenix Suns",
    "por": "Portland Trail Blazers", "sac": "Sacramento Kings", "sas": "San Antonio Spurs",
    "sa": "San Antonio Spurs", "tor": "Toronto Raptors", "uta": "Utah Jazz",
    "was": "Washington Wizards",
    "hawks": "Atlanta Hawks", "celtics": "Boston Celtics", "nets": "Brooklyn Nets",
    "hornets": "Charlotte Hornets", "bulls": "Chicago Bulls", "cavaliers": "Cleveland Cavaliers",
    "cavs": "Cleveland Cavaliers", "mavericks": "Dallas Mavericks", "mavs": "Dallas Mavericks",
    "nuggets": "Denver Nuggets", "pistons": "Detroit Pistons", "warriors": "Golden State Warriors",
    "rockets": "Houston Rockets", "pacers": "Indiana Pacers", "clippers": "Los Angeles Clippers",
    "lakers": "Los Angeles Lakers", "grizzlies": "Memphis Grizzlies", "heat": "Miami Heat",
    "bucks": "Milwaukee Bucks", "timberwolves": "Minnesota Timberwolves",
    "wolves": "Minnesota Timberwolves", "pelicans": "New Orleans Pelicans",
    "knicks": "New York Knicks", "thunder": "Oklahoma City Thunder", "magic": "Orlando Magic",
    "76ers": "Philadelphia 76ers", "sixers": "Philadelphia 76ers", "suns": "Phoenix Suns",
    "blazers": "Portland Trail Blazers", "trail blazers": "Portland Trail Blazers",
    "kings": "Sacramento Kings", "spurs": "San Antonio Spurs", "raptors": "Toronto Raptors",
    "jazz": "Utah Jazz", "wizards": "Washington Wizards",
}


def normalize_team(raw: str | None) -> str | None:
    """Return the canonical NBA team name for a free-form source string.

    Returns ``None`` when the input cannot be resolved — callers log and
    skip rather than guess. Unresolvable names are almost always a
    data-source issue worth surfacing, not papering over.
    """
    if not raw:
        return None
    key = raw.strip().lower()
    # Strip leading "la " that some feeds use for Clippers/Lakers disambig.
    if key in _ALIASES:
        return _ALIASES[key]
    key_stripped = re.sub(r"\s+", " ", key)
    return _ALIASES.get(key_stripped)


@dataclass(frozen=True, slots=True)
class IngestResult:
    games_inserted: int = 0
    games_skipped: int = 0
    odds_inserted: int = 0
    odds_skipped: int = 0
    odds_unmatched: int = 0


# ---------- Game-results ingest (nba_api) ----------


_SEASON_SHORT = re.compile(r"^\d{4}-\d{2}$")
_SEASON_LONG = re.compile(r"^(\d{4})-(\d{4})$")


def _season_to_nba_api(season: str) -> str:
    """Normalize season strings to nba_api's ``YYYY-YY`` format."""
    if _SEASON_SHORT.fullmatch(season):
        return season
    m = _SEASON_LONG.fullmatch(season)
    if m:
        start, end = m.group(1), m.group(2)
        if int(end) != int(start) + 1:
            raise ValueError(f"Non-consecutive season years: {season!r}")
        return f"{start}-{end[-2:]}"
    raise ValueError(f"Unrecognized season format: {season!r} (expected '2023-24')")


def db_season_key(season: str) -> str:
    """Translate a user season (e.g. ``2023-24``) to the DB ``season`` tag."""
    return f"{_season_to_nba_api(season)}-real"


def ingest_nba_games(
    session: Session,
    season: str,
    *,
    fetch_fn: Callable[[str], list[dict[str, Any]]] | None = None,
) -> IngestResult:
    """Pull completed NBA regular-season games for ``season`` and upsert.

    ``fetch_fn`` is a test seam: when provided it replaces the live
    ``nba_api`` call. It must return a list of dicts shaped like the
    ``LeagueGameFinder`` response (one row per team-game, keys
    ``GAME_ID``, ``GAME_DATE``, ``TEAM_NAME``, ``MATCHUP``, ``PTS``,
    ``WL``). Keeps the function unit-testable without network.
    """
    nba_season = _season_to_nba_api(season)
    raw_rows = fetch_fn(nba_season) if fetch_fn else _fetch_nba_games(nba_season)

    # Each game appears twice in the feed (one row per team). Collapse to
    # one record per GAME_ID, tagging the home/away sides via MATCHUP:
    # nba_api convention: " vs. " = home, " @ " = away.
    by_game: dict[str, dict[str, Any]] = {}
    for r in raw_rows:
        gid = str(r["GAME_ID"])
        matchup = str(r["MATCHUP"])
        is_home = " vs. " in matchup
        slot = by_game.setdefault(gid, {"home": None, "away": None, "date": r["GAME_DATE"]})
        slot["home" if is_home else "away"] = {
            "team": str(r["TEAM_NAME"]),
            "pts": int(r["PTS"]),
        }

    db_season = db_season_key(season)
    existing_ext_ids = set(
        session.scalars(
            select(HistoricalGame.external_id).where(HistoricalGame.season == db_season)
        ).all()
    )

    inserted = skipped = 0
    for gid, data in by_game.items():
        if not (data["home"] and data["away"]):
            continue  # Incomplete pair — rare nba_api hiccup, skip silently.

        ext_id = f"nba-{gid}"
        if ext_id in existing_ext_ids:
            skipped += 1
            continue

        parsed = _coerce_date(data["date"])
        if parsed is None:
            logger.warning(
                "ingest_nba_games: could not parse date %r for game %s",
                data["date"], gid,
            )
            continue
        # Commence time unknown at day-granularity; anchor at 7pm UTC for ordering.
        commence = datetime.combine(parsed, time(hour=19), tzinfo=UTC)

        home_score = data["home"]["pts"]
        away_score = data["away"]["pts"]
        winner = "home" if home_score > away_score else "away"

        session.add(
            HistoricalGame(
                external_id=ext_id,
                sport="NBA",
                season=db_season,
                commence_time=commence,
                home_team=data["home"]["team"],
                away_team=data["away"]["team"],
                home_score=home_score,
                away_score=away_score,
                winner=winner,
            )
        )
        inserted += 1

    session.commit()
    return IngestResult(games_inserted=inserted, games_skipped=skipped)


def _fetch_nba_games(nba_season: str) -> list[dict[str, Any]]:  # pragma: no cover
    """Live call into nba_api; bypassed in tests via the ``fetch_fn`` seam."""
    try:
        from nba_api.stats.endpoints import leaguegamefinder
    except ImportError as e:
        raise RuntimeError(
            "nba_api is not installed. Install the 'ml' extras: pip install -e '.[ml]'"
        ) from e

    finder = leaguegamefinder.LeagueGameFinder(
        season_nullable=nba_season,
        season_type_nullable="Regular Season",
        league_id_nullable="00",  # "00" = NBA
    )
    df = finder.get_data_frames()[0]
    return list(df.to_dict(orient="records"))


# ---------- CSV odds ingest ----------


@dataclass(frozen=True, slots=True)
class _OddsRow:
    day: date
    home_team: str
    away_team: str
    book: str
    home_ml: int
    away_ml: int


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).replace("+", "").strip())
    except ValueError:
        return None


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str):
        return None
    s = value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%Y/%m/%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _read_odds_csv(path: Path) -> list[_OddsRow]:
    """Parse a moneyline CSV. See ``ingest_odds_csv`` for the schema."""
    rows: list[_OddsRow] = []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: no header row")
        headers = {h.lower().strip(): h for h in reader.fieldnames}
        required = {"date", "home_team", "away_team", "home_ml", "away_ml"}
        missing = required - headers.keys()
        if missing:
            raise ValueError(f"{path}: missing required columns: {sorted(missing)}")

        has_book = "book" in headers
        for line_no, raw in enumerate(reader, start=2):
            day = _coerce_date(raw[headers["date"]])
            home = normalize_team(raw[headers["home_team"]])
            away = normalize_team(raw[headers["away_team"]])
            home_ml = _parse_int(raw[headers["home_ml"]])
            away_ml = _parse_int(raw[headers["away_ml"]])
            if day is None or home is None or away is None or home_ml is None or away_ml is None:
                logger.warning("odds csv %s line %d: skipped (unparseable)", path.name, line_no)
                continue
            book = (raw[headers["book"]].strip() if has_book else "") or "consensus"
            rows.append(
                _OddsRow(
                    day=day, home_team=home, away_team=away,
                    book=book, home_ml=home_ml, away_ml=away_ml,
                )
            )
    return rows


def ingest_odds_csv(
    session: Session,
    path: Path,
    *,
    season: str,
    market: str = "h2h",
) -> IngestResult:
    """Attach moneylines from a CSV to already-ingested games for ``season``.

    CSV schema (case-insensitive, any column order):
        date, home_team, away_team, home_ml, away_ml, [book]

    - ``date`` is calendar-day (UTC) of the game. Team names may be full
      ("Boston Celtics"), abbreviation ("BOS"), or mascot ("Celtics");
      all normalize to the nba_api canonical form.
    - ``home_ml``/``away_ml`` are American odds (e.g. -150, +130).
    - ``book`` defaults to "consensus" when absent.

    Matching: (commence_date, home_team, away_team) against
    ``historical_games`` filtered to ``sport='NBA'`` and
    ``season='<season>-real'``. Rows that don't match are counted
    (``odds_unmatched``) and logged, not fatal.
    """
    db_season = db_season_key(season)
    rows = _read_odds_csv(path)

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

    inserted = skipped = unmatched = 0
    for row in rows:
        game = games_by_key.get((row.day, row.home_team, row.away_team))
        if game is None:
            unmatched += 1
            continue
        for outcome, ml in ((game.home_team, row.home_ml), (game.away_team, row.away_ml)):
            key = (game.id, row.book, market, outcome)
            if key in existing_odds_keys:
                skipped += 1
                continue
            session.add(
                HistoricalOdds(
                    game_id=game.id,
                    book=row.book,
                    market=market,
                    outcome=outcome,
                    american_odds=ml,
                )
            )
            existing_odds_keys.add(key)
            inserted += 1

    session.commit()
    return IngestResult(
        odds_inserted=inserted, odds_skipped=skipped, odds_unmatched=unmatched,
    )
