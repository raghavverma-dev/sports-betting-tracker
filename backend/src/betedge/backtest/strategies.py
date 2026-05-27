"""Betting strategies evaluated by the backtest engine.

A strategy is a pure function that takes per-game inputs (book quotes,
some probability estimate) and returns either a bet decision or None.
Keeping strategies pure makes them trivial to unit-test, and lets us
swap the probability source (market consensus today, ML model tomorrow)
without touching the engine.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from betedge.services.odds_math import ev_percent, kelly_fraction, payout


@dataclass(frozen=True, slots=True)
class GameQuote:
    """All inputs a strategy needs to make one decision for one game."""

    game_id: int
    selection: str
    american_odds: int
    book: str
    market_probability: float
    predicted_probability: float


@dataclass(frozen=True, slots=True)
class BetDecision:
    selection: str
    american_odds: int
    book: str
    stake: float
    potential_payout: float
    predicted_probability: float
    market_probability: float


class Strategy(ABC):
    name: str

    @abstractmethod
    def decide(self, quote: GameQuote, bankroll: float) -> BetDecision | None:
        """Return a bet decision, or None to skip."""


class MarketBaseline(Strategy):
    """No-op strategy — makes no bets, used purely to measure forecast
    quality (Brier / log loss / calibration) against the market."""

    name = "market-baseline"

    def decide(self, quote: GameQuote, bankroll: float) -> BetDecision | None:  # noqa: ARG002
        return None


@dataclass
class FlatEvThreshold(Strategy):
    """Bet a fixed fraction of bankroll whenever EV exceeds a threshold."""

    name = "flat-ev-threshold"
    min_ev: float = 2.0
    stake_percent: float = 1.0

    def decide(self, quote: GameQuote, bankroll: float) -> BetDecision | None:
        ev = ev_percent(quote.predicted_probability, quote.american_odds)
        if ev < self.min_ev:
            return None
        stake = round(bankroll * self.stake_percent / 100.0, 2)
        if stake < 1.0:
            return None
        return BetDecision(
            selection=quote.selection,
            american_odds=quote.american_odds,
            book=quote.book,
            stake=stake,
            potential_payout=round(payout(stake, quote.american_odds), 2),
            predicted_probability=quote.predicted_probability,
            market_probability=quote.market_probability,
        )


@dataclass
class KellyEvThreshold(Strategy):
    """Classic +EV strategy: fractional Kelly sized, capped by max stake."""

    name = "kelly-ev-threshold"
    min_ev: float = 2.0
    kelly_fraction_value: float = 0.25
    max_stake_percent: float = 5.0

    def decide(self, quote: GameQuote, bankroll: float) -> BetDecision | None:
        ev = ev_percent(quote.predicted_probability, quote.american_odds)
        if ev < self.min_ev:
            return None

        full_kelly = kelly_fraction(quote.predicted_probability, quote.american_odds)
        if full_kelly <= 0:
            return None

        fraction = min(full_kelly * self.kelly_fraction_value, self.max_stake_percent / 100.0)
        stake = round(bankroll * fraction, 2)
        if stake < 1.0:
            return None

        return BetDecision(
            selection=quote.selection,
            american_odds=quote.american_odds,
            book=quote.book,
            stake=stake,
            potential_payout=round(payout(stake, quote.american_odds), 2),
            predicted_probability=quote.predicted_probability,
            market_probability=quote.market_probability,
        )


def build_strategy(name: str, **params: float) -> Strategy:
    """Factory so the API can dispatch on a string name from a request body."""
    if name == MarketBaseline.name:
        return MarketBaseline()
    if name == FlatEvThreshold.name:
        return FlatEvThreshold(
            min_ev=params.get("min_ev", 2.0),
            stake_percent=params.get("stake_percent", 1.0),
        )
    if name == KellyEvThreshold.name:
        return KellyEvThreshold(
            min_ev=params.get("min_ev", 2.0),
            kelly_fraction_value=params.get("kelly_fraction", 0.25),
            max_stake_percent=params.get("max_stake_percent", 5.0),
        )
    raise ValueError(f"Unknown strategy: {name}")
