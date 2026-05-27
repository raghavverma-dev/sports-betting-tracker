from __future__ import annotations

import math

import pytest

from betedge.backtest.metrics import (
    brier_score,
    calibration_curve,
    log_loss,
    max_drawdown,
    roi,
)


def test_brier_perfect_forecaster_is_zero() -> None:
    assert brier_score([1.0, 0.0, 1.0], [1.0, 0.0, 1.0]) == 0.0


def test_brier_uninformative_on_coinflip() -> None:
    # Always predicting 0.5 on a balanced series => Brier = 0.25.
    assert brier_score([0.5] * 4, [1, 0, 1, 0]) == pytest.approx(0.25)


def test_brier_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        brier_score([0.5, 0.5], [1])


def test_log_loss_perfect_is_near_zero() -> None:
    # Not exactly zero because of the eps clip (log(1-eps) > log(1)).
    assert log_loss([0.999, 0.001], [1.0, 0.0]) < 0.01


def test_log_loss_wrong_confident_prediction_is_large() -> None:
    # Confidently wrong => very high loss but finite thanks to clipping.
    value = log_loss([0.001], [1.0])
    assert value > 5
    assert math.isfinite(value)


def test_calibration_bins_are_monotonic_and_complete() -> None:
    preds = [i / 100 for i in range(100)]
    outs = [1.0 if p > 0.5 else 0.0 for p in preds]
    bins = calibration_curve(preds, outs, n_bins=10)
    assert len(bins) == 10
    assert [b.bin_lower for b in bins] == [i / 10 for i in range(10)]
    # Every bin is populated for a uniform input.
    assert all(b.count > 0 for b in bins)


def test_calibration_handles_edge_probability_of_one() -> None:
    # p=1.0 must land in the final bin (inclusive upper edge).
    bins = calibration_curve([1.0], [1.0], n_bins=10)
    assert bins[-1].count == 1
    assert bins[-1].predicted_mean == 1.0


def test_max_drawdown_flat_curve_is_zero() -> None:
    assert max_drawdown([1000, 1000, 1000]) == 0.0


def test_max_drawdown_peak_to_trough() -> None:
    curve = [1000, 1100, 900, 950, 800, 1200]
    # Largest drop: 1100 -> 800 = 300 / 1100 = ~0.2727
    assert max_drawdown(curve) == pytest.approx(300 / 1100, rel=1e-6)


def test_roi_basic() -> None:
    assert roi(1000, 1200) == pytest.approx(20.0)
    assert roi(1000, 800) == pytest.approx(-20.0)
    assert roi(0, 100) == 0.0
