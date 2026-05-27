"""American-odds arithmetic used throughout the system.

These helpers are pure and deterministic — a useful property for tests
and for porting between languages (the frontend has a parallel copy in
src/utils/odds.ts).
"""

from __future__ import annotations


def american_to_decimal(american: int) -> float:
    """Convert American odds to decimal (European) odds."""
    if american > 0:
        return american / 100 + 1
    return 100 / abs(american) + 1


def implied_probability(american: int) -> float:
    """The probability implied by a single book's American odds, with vig."""
    if american > 0:
        return 100 / (american + 100)
    return abs(american) / (abs(american) + 100)


def probability_to_american(prob: float) -> int:
    """Fair American odds corresponding to a probability."""
    if not 0 < prob < 1:
        raise ValueError(f"probability must be in (0, 1), got {prob}")
    if prob >= 0.5:
        return round(-100 * prob / (1 - prob))
    return round(100 * (1 - prob) / prob)


def payout(stake: float, american: int) -> float:
    """Total return (stake + profit) if a bet at American odds wins."""
    return stake * american_to_decimal(american)


def ev_percent(true_prob: float, american: int) -> float:
    """Expected value as a percent of stake, given a true probability."""
    return (true_prob * american_to_decimal(american) - 1) * 100


def kelly_fraction(true_prob: float, american: int) -> float:
    """Full-Kelly stake as a fraction of bankroll.

    Returns 0 if there is no edge (i.e. bookmaker's price implies ≥
    true probability). Callers should typically scale this down (quarter
    or eighth Kelly) before using it to size a real stake.
    """
    decimal = american_to_decimal(american)
    b = decimal - 1
    p = true_prob
    q = 1 - p
    k = (b * p - q) / b
    return max(0.0, k)
