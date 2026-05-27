from __future__ import annotations

import pytest

from betedge.services.odds_math import (
    american_to_decimal,
    ev_percent,
    implied_probability,
    kelly_fraction,
    payout,
    probability_to_american,
)


def test_american_to_decimal_positive() -> None:
    assert american_to_decimal(100) == pytest.approx(2.0)
    assert american_to_decimal(200) == pytest.approx(3.0)


def test_american_to_decimal_negative() -> None:
    assert american_to_decimal(-200) == pytest.approx(1.5)
    assert american_to_decimal(-110) == pytest.approx(1.9090909, rel=1e-4)


def test_implied_probability_is_consistent_with_decimal() -> None:
    # decimal = 1 / true_prob ignores vig — but implied_probability is
    # the single-book implied prob, so decimal * implied = 1 exactly.
    for odds in (-300, -150, -110, 100, 140, 300):
        assert implied_probability(odds) * american_to_decimal(odds) == pytest.approx(1.0)


def test_probability_to_american_is_inverse_of_implied() -> None:
    for p in (0.1, 0.25, 0.4, 0.5, 0.55, 0.75, 0.9):
        recovered = implied_probability(probability_to_american(p))
        assert recovered == pytest.approx(p, abs=0.01)


def test_probability_to_american_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        probability_to_american(0.0)
    with pytest.raises(ValueError):
        probability_to_american(1.0)


def test_payout_formula() -> None:
    assert payout(100, 100) == pytest.approx(200)
    assert payout(100, -110) == pytest.approx(190.909, abs=0.01)
    assert payout(50, 150) == pytest.approx(125)


def test_ev_positive_when_prob_exceeds_implied() -> None:
    # +100 odds implies 50%. If we think it's really 60%, EV > 0.
    assert ev_percent(0.6, 100) > 0
    # And the opposite.
    assert ev_percent(0.4, 100) < 0
    # Zero at exact break-even, modulo float noise.
    assert ev_percent(0.5, 100) == pytest.approx(0.0, abs=1e-9)


def test_kelly_fraction_zero_when_no_edge() -> None:
    assert kelly_fraction(0.5, 100) == pytest.approx(0.0, abs=1e-9)
    # Negative EV => Kelly returns 0 (not a negative number).
    assert kelly_fraction(0.4, 100) == 0.0


def test_kelly_fraction_matches_reference_formula() -> None:
    # (bp - q)/b with b=1 (i.e. +100 odds) and p=0.6 => (0.6 - 0.4)/1 = 0.2
    assert kelly_fraction(0.6, 100) == pytest.approx(0.2, abs=1e-9)
