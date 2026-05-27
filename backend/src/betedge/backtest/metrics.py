"""Forecast-quality and portfolio metrics used by the backtest engine.

Deliberately written with no numpy/pandas dependency so the metrics can
be called from small unit tests without fixtures or global state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    bin_lower: float
    bin_upper: float
    predicted_mean: float
    empirical_mean: float
    count: int


def brier_score(predictions: list[float], outcomes: list[float]) -> float:
    """Mean squared error between predicted probability and binary outcome.

    Lower is better. For a reference: an uninformative forecast always
    predicting 0.5 on a 50/50 event has Brier = 0.25. A well-calibrated
    sportsbook market typically sits around 0.21-0.23 for NBA h2h.
    """
    if not predictions:
        raise ValueError("predictions must be non-empty")
    if len(predictions) != len(outcomes):
        raise ValueError("predictions and outcomes length mismatch")

    return sum((p - y) ** 2 for p, y in zip(predictions, outcomes, strict=True)) / len(predictions)


def log_loss(predictions: list[float], outcomes: list[float], *, eps: float = 1e-12) -> float:
    """Average negative log-likelihood of observing the actual outcomes.

    Clips predictions to (eps, 1-eps) to avoid -inf when a model
    confidently predicts the wrong side.
    """
    if not predictions:
        raise ValueError("predictions must be non-empty")
    if len(predictions) != len(outcomes):
        raise ValueError("predictions and outcomes length mismatch")

    total = 0.0
    for p, y in zip(predictions, outcomes, strict=True):
        p_clip = min(max(p, eps), 1 - eps)
        total += -(y * math.log(p_clip) + (1 - y) * math.log(1 - p_clip))
    return total / len(predictions)


def calibration_curve(
    predictions: list[float],
    outcomes: list[float],
    *,
    n_bins: int = 10,
) -> list[CalibrationBin]:
    """Bin predictions into equal-width buckets and compare predicted vs
    empirical win rate in each.

    A well-calibrated forecaster has `predicted_mean ≈ empirical_mean`
    in every bucket with a non-trivial count.
    """
    if n_bins < 2:
        raise ValueError("n_bins must be >= 2")
    if len(predictions) != len(outcomes):
        raise ValueError("predictions and outcomes length mismatch")

    buckets: list[tuple[float, float, list[float], list[float]]] = []
    for i in range(n_bins):
        lo = i / n_bins
        hi = (i + 1) / n_bins
        buckets.append((lo, hi, [], []))

    for p, y in zip(predictions, outcomes, strict=True):
        # Last bin is inclusive on the upper edge so p=1.0 lands somewhere.
        idx = min(int(p * n_bins), n_bins - 1)
        buckets[idx][2].append(p)
        buckets[idx][3].append(y)

    result: list[CalibrationBin] = []
    for lo, hi, preds, ys in buckets:
        count = len(preds)
        if count == 0:
            predicted_mean = (lo + hi) / 2
            empirical_mean = float("nan")
        else:
            predicted_mean = sum(preds) / count
            empirical_mean = sum(ys) / count
        result.append(
            CalibrationBin(
                bin_lower=lo,
                bin_upper=hi,
                predicted_mean=predicted_mean,
                empirical_mean=empirical_mean,
                count=count,
            )
        )
    return result


def max_drawdown(equity_curve: list[float]) -> float:
    """Largest peak-to-trough drop along the curve, expressed as a fraction.

    Returns 0.0 if the curve is strictly non-decreasing or empty.
    """
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            drawdown = (peak - value) / peak
            worst = max(worst, drawdown)
    return worst


def roi(initial: float, final: float) -> float:
    """Return on investment as a percentage."""
    if initial <= 0:
        return 0.0
    return (final - initial) / initial * 100.0
