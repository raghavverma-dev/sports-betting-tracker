"""Bet ranking — de-vig, market consensus, EV, stale/outlier detection.

Port of src/utils/ranking.ts kept intentionally similar in shape so the
two implementations can be diffed line-for-line during reviews.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from betedge.services.odds_math import (
    ev_percent as calc_ev,
)
from betedge.services.odds_math import (
    implied_probability,
    probability_to_american,
)

STALE_THRESHOLD = timedelta(minutes=10)
OUTLIER_PROB_GAP = 0.05
MIN_BOOKS_FOR_OUTLIER = 3


@dataclass(slots=True)
class BookQuote:
    book: str
    odds: int
    last_update: datetime | None = None


@dataclass(slots=True)
class RankedBet:
    id: str
    game_id: str
    sport: str
    event: str
    commence_time: datetime
    selection: str
    bet_type: str
    best_odds: int
    best_book: str
    avg_odds: int
    market_probability: float
    implied_probability: float
    ev: float
    num_books: int
    all_books: list[BookQuote]
    stale_warning: bool = False
    outlier_warning: bool = False
    stale_minutes: int = 0
    adjusted_ev: float | None = None
    adjusted_best_odds: int | None = None
    adjusted_best_book: str | None = None
    adjusted_market_probability: float | None = None
    devigged_probs: list[tuple[str, float]] = field(default_factory=list)


def _parse_ts(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def rank_bets(games: list[dict[str, Any]]) -> list[RankedBet]:
    """Given The Odds API payload for one or more sports, return ranked bets.

    Algorithm:
      1. Aggregate per-outcome quotes from every book.
      2. De-vig each book's market (divide each side's implied probability
         by the book's overround) to recover fair probabilities.
      3. Average de-vigged probabilities across books = market consensus.
      4. EV = (consensus * best_decimal_odds - 1) * 100 percent.
      5. Flag stale (>=10min lag behind freshest quote) and outlier
         (>5pp gap vs consensus-excluding-best) best-books; recompute
         EV against the next-best clean book for those rows.

    Results are sorted descending by adjusted_ev (when present) or ev.
    """
    ranked_by_key: dict[str, RankedBet] = {}

    for game in games:
        sport = game.get("sport_key", game.get("sport", "UNKNOWN"))
        event = f"{game.get('away_team', '?')} @ {game.get('home_team', '?')}"
        commence = _parse_ts(game.get("commence_time")) or datetime.now(UTC)

        for bookmaker in game.get("bookmakers", []):
            book_title = bookmaker.get("title", bookmaker.get("key", "?"))
            last_update = _parse_ts(bookmaker.get("last_update"))

            for market in bookmaker.get("markets", []):
                market_key = market["key"]
                outcomes = market.get("outcomes", [])
                overround = sum(implied_probability(o["price"]) for o in outcomes)
                if overround <= 0:
                    continue

                for outcome in outcomes:
                    point = outcome.get("point")
                    point_suffix = f"-{point}" if point is not None else ""
                    selection = (
                        f"{outcome['name']} {point}" if point is not None else outcome["name"]
                    )
                    key = f"{game['id']}-{market_key}-{outcome['name']}{point_suffix}"

                    rb = ranked_by_key.get(key)
                    if rb is None:
                        rb = RankedBet(
                            id=key,
                            game_id=game["id"],
                            sport=sport,
                            event=event,
                            commence_time=commence,
                            selection=selection,
                            bet_type=market_key,
                            best_odds=outcome["price"],
                            best_book=book_title,
                            avg_odds=0,
                            market_probability=0.0,
                            implied_probability=0.0,
                            ev=0.0,
                            num_books=0,
                            all_books=[],
                        )
                        ranked_by_key[key] = rb

                    rb.all_books.append(BookQuote(book_title, outcome["price"], last_update))
                    fair = implied_probability(outcome["price"]) / overround
                    rb.devigged_probs.append((book_title, fair))

                    if outcome["price"] > rb.best_odds:
                        rb.best_odds = outcome["price"]
                        rb.best_book = book_title

    for rb in ranked_by_key.values():
        rb.num_books = len(rb.all_books)
        if rb.devigged_probs:
            rb.market_probability = sum(p for _, p in rb.devigged_probs) / len(rb.devigged_probs)
            rb.avg_odds = probability_to_american(max(min(rb.market_probability, 0.999), 0.001))

        rb.implied_probability = implied_probability(rb.best_odds)
        rb.ev = calc_ev(rb.market_probability, rb.best_odds)

        _flag_warnings(rb)
        _compute_adjusted(rb)

    result = list(ranked_by_key.values())
    result.sort(key=lambda r: r.adjusted_ev if r.adjusted_ev is not None else r.ev, reverse=True)
    return result


def _flag_warnings(rb: RankedBet) -> None:
    timestamps = [q.last_update for q in rb.all_books if q.last_update is not None]
    if len(timestamps) >= 2:
        freshest = max(timestamps)
        best_book_ts = next(
            (q.last_update for q in rb.all_books if q.book == rb.best_book and q.last_update),
            None,
        )
        if best_book_ts is not None:
            lag = freshest - best_book_ts
            rb.stale_minutes = int(lag.total_seconds() // 60)
            rb.stale_warning = lag >= STALE_THRESHOLD

    if rb.num_books >= MIN_BOOKS_FOR_OUTLIER:
        others = [p for book, p in rb.devigged_probs if book != rb.best_book]
        if others:
            consensus_excl = sum(others) / len(others)
            if consensus_excl - rb.implied_probability > OUTLIER_PROB_GAP:
                rb.outlier_warning = True


def _compute_adjusted(rb: RankedBet) -> None:
    if not (rb.stale_warning or rb.outlier_warning):
        return

    timestamps = [q.last_update for q in rb.all_books if q.last_update is not None]
    freshest = max(timestamps) if timestamps else None

    clean_books = [
        q
        for q in rb.all_books
        if q.book != rb.best_book
        and (
            q.last_update is None
            or freshest is None
            or (freshest - q.last_update) < STALE_THRESHOLD
        )
    ]
    if not clean_books:
        return

    clean_books.sort(key=lambda q: q.odds, reverse=True)
    next_best = clean_books[0]
    clean_names = {q.book for q in clean_books}
    clean_probs = [p for book, p in rb.devigged_probs if book in clean_names]
    if not clean_probs:
        return

    clean_market = sum(clean_probs) / len(clean_probs)
    rb.adjusted_best_odds = next_best.odds
    rb.adjusted_best_book = next_best.book
    rb.adjusted_market_probability = clean_market
    rb.adjusted_ev = calc_ev(clean_market, next_best.odds)
