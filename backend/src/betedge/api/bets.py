"""Manual bet tracking API."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from betedge.db import get_session
from betedge.models import BankrollEvent, Bet
from betedge.schemas import (
    BankrollEventOut,
    BankrollSnapshot,
    BetCreate,
    BetOut,
    BetStatusUpdate,
)
from betedge.services.odds_math import (
    ev_percent,
    implied_probability,
    kelly_fraction,
    payout,
)

router = APIRouter(prefix="/bets", tags=["bets"])

INITIAL_BANKROLL = 1000.0


def _current_bankroll(session: Session) -> float:
    total = session.scalar(
        select(BankrollEvent.balance_after)
        .order_by(BankrollEvent.occurred_at.desc(), BankrollEvent.id.desc())
        .limit(1)
    )
    return total if total is not None else INITIAL_BANKROLL


def _record_event(
    session: Session,
    *,
    delta: float,
    reason: str,
    bet_id: int | None = None,
) -> BankrollEvent:
    new_balance = round(_current_bankroll(session) + delta, 2)
    event = BankrollEvent(
        delta=delta,
        balance_after=new_balance,
        reason=reason,
        bet_id=bet_id,
    )
    session.add(event)
    return event


@router.get("", response_model=list[BetOut])
def list_bets(
    sport: str | None = None,
    status_filter: str | None = None,
    session: Session = Depends(get_session),
) -> list[Bet]:
    stmt = select(Bet).order_by(Bet.placed_at.desc())
    if sport:
        stmt = stmt.where(Bet.sport == sport)
    if status_filter:
        stmt = stmt.where(Bet.status == status_filter)
    return list(session.scalars(stmt).all())


@router.post("", response_model=BetOut, status_code=status.HTTP_201_CREATED)
def create_bet(
    payload: BetCreate,
    session: Session = Depends(get_session),
) -> Bet:
    implied = implied_probability(payload.odds)
    expected_value = (
        ev_percent(payload.estimated_probability, payload.odds)
        if payload.estimated_probability is not None
        else None
    )
    kelly = (
        kelly_fraction(payload.estimated_probability, payload.odds)
        if payload.estimated_probability is not None
        else None
    )

    bet = Bet(
        sport=payload.sport,
        bet_type=payload.bet_type,
        status="pending",
        event=payload.event,
        selection=payload.selection,
        odds=payload.odds,
        stake=payload.stake,
        potential_payout=round(payout(payload.stake, payload.odds), 2),
        actual_payout=None,
        placed_at=datetime.now(UTC),
        sportsbook=payload.sportsbook,
        notes=payload.notes,
        estimated_probability=payload.estimated_probability,
        implied_probability=implied,
        expected_value=expected_value,
        kelly_stake=kelly,
    )
    session.add(bet)
    session.flush()

    _record_event(session, delta=-payload.stake, reason="bet_placed", bet_id=bet.id)
    session.commit()
    session.refresh(bet)
    return bet


@router.patch("/{bet_id}/status", response_model=BetOut)
def update_bet_status(
    bet_id: int,
    payload: BetStatusUpdate,
    session: Session = Depends(get_session),
) -> Bet:
    bet = session.get(Bet, bet_id)
    if bet is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bet not found")

    # Reverse any prior settlement so state transitions compose cleanly
    # (e.g. won -> lost correctly takes the payout back out).
    reversal_delta = 0.0
    if bet.status == "won" or bet.status == "push":
        reversal_delta = -(bet.actual_payout or 0.0)
    # pending and lost require no reversal; their contribution is baked into
    # the bankroll ledger already (-stake at placement for both).

    new_status = payload.status
    new_payout: float | None
    delta = reversal_delta
    if new_status == "won":
        new_payout = bet.potential_payout
        delta += new_payout
    elif new_status == "push":
        new_payout = bet.stake
        delta += new_payout
    elif new_status == "lost":
        new_payout = 0.0
    else:  # pending
        new_payout = None

    bet.status = new_status
    bet.actual_payout = new_payout
    bet.settled_at = datetime.now(UTC) if new_status != "pending" else None

    if delta != 0.0:
        _record_event(
            session,
            delta=delta,
            reason=f"settle_{new_status}",
            bet_id=bet.id,
        )

    session.commit()
    session.refresh(bet)
    return bet


@router.delete("/{bet_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bet(
    bet_id: int,
    session: Session = Depends(get_session),
) -> None:
    bet = session.get(Bet, bet_id)
    if bet is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bet not found")

    # Reverse the bet's full impact on the bankroll. For pending bets
    # actual_payout is None, so this reduces to refunding the stake.
    refund = bet.stake - (bet.actual_payout or 0.0)
    if refund != 0.0:
        _record_event(session, delta=refund, reason="bet_deleted", bet_id=None)

    session.delete(bet)
    session.commit()


@router.get("/bankroll/snapshot", response_model=BankrollSnapshot)
def bankroll_snapshot(session: Session = Depends(get_session)) -> BankrollSnapshot:
    history = list(
        session.scalars(
            select(BankrollEvent).order_by(BankrollEvent.occurred_at.asc(), BankrollEvent.id.asc())
        ).all()
    )
    current = history[-1].balance_after if history else INITIAL_BANKROLL

    total_wagered = sum(-h.delta for h in history if h.delta < 0 and h.reason == "bet_placed")
    total_returned = sum(h.delta for h in history if h.delta > 0 and h.reason.startswith("settle_"))

    return BankrollSnapshot(
        current_balance=round(current, 2),
        initial_balance=INITIAL_BANKROLL,
        total_wagered=round(total_wagered, 2),
        total_returned=round(total_returned, 2),
        history=[BankrollEventOut.model_validate(h) for h in history],
    )
