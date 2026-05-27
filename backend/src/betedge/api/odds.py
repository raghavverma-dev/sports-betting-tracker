"""Live-odds proxy. Keeps The Odds API key on the server side."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from betedge.config import Settings, get_settings
from betedge.schemas import BookOdds, RankedBetOut
from betedge.services.odds_client import OddsApiClient, OddsApiError
from betedge.services.ranking import RankedBet, rank_bets

router = APIRouter(prefix="/odds", tags=["odds"])


def _to_schema(rb: RankedBet) -> RankedBetOut:
    return RankedBetOut(
        id=rb.id,
        game_id=rb.game_id,
        sport=rb.sport,
        event=rb.event,
        commence_time=rb.commence_time,
        selection=rb.selection,
        bet_type=rb.bet_type,
        best_odds=rb.best_odds,
        best_book=rb.best_book,
        avg_odds=rb.avg_odds,
        market_probability=rb.market_probability,
        implied_probability=rb.implied_probability,
        ev=rb.ev,
        num_books=rb.num_books,
        all_books=[
            BookOdds(book=q.book, odds=q.odds, last_update=q.last_update)
            for q in rb.all_books
        ],
        stale_warning=rb.stale_warning,
        outlier_warning=rb.outlier_warning,
    )


@router.get("/ranked", response_model=list[RankedBetOut])
def ranked_odds(
    sport: str,
    market: str = "h2h",
    settings: Settings = Depends(get_settings),
) -> list[RankedBetOut]:
    try:
        with OddsApiClient(settings) as client:
            games = client.fetch_odds(sport, market)
    except OddsApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    ranked = rank_bets(games)
    return [_to_schema(r) for r in ranked]
