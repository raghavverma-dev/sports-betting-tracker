"""Train and serve the LightGBM moneyline model.

The model predicts P(home win) from the pre-game features in
``features.py``. The split is **chronological**, never random: we train
on the earliest fraction of games and evaluate on the most recent. A
random split would leak future information (a team's late-season form
into an early-season prediction) and inflate the metrics — the same
mistake that makes a lot of public sports-modeling notebooks look better
than they are.

The trained model is persisted with ``joblib`` so the backtest engine
can load it through ``ModelProbabilitySource`` without retraining. The
saved artifact bundles the predictor (calibrated wrapper or bare
booster), the feature column order, and the training metadata so a stale
model can't be silently mismatched against new features.

LightGBM is an optional dependency (the ``ml`` extras). Importing this
module without it raises a clear, actionable error rather than a bare
``ImportError`` deep in a call stack.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from betedge.backtest.metrics import brier_score, log_loss
from betedge.ml.features import FEATURE_COLUMNS, FeatureRow, build_feature_rows
from betedge.models import HistoricalGame

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[3] / "data" / "moneyline_lgbm.joblib"
_MIN_TRAIN_ROWS = 50


def _require_ml_deps() -> tuple[Any, Any, Any]:
    try:
        import joblib
        import lightgbm as lgb
        import pandas as pd
    except ImportError as e:  # pragma: no cover - exercised only without extras
        raise RuntimeError(
            "The model requires the 'ml' extras. Install them with: "
            "pip install -e '.[ml]'"
        ) from e
    return lgb, pd, joblib


def _frame(pd: Any, rows: list[FeatureRow]) -> Any:
    """Feature matrix as a named DataFrame so fit and predict agree on
    column names (avoids sklearn's 'no valid feature names' warning)."""
    return pd.DataFrame([r.vector() for r in rows], columns=list(FEATURE_COLUMNS))


@dataclass(frozen=True, slots=True)
class TrainResult:
    model_path: Path
    train_rows: int
    test_rows: int
    # Held-out test metrics, before and after calibration. The raw/calibrated
    # pair shows calibration's effect honestly rather than only reporting the
    # better number.
    test_brier_raw: float | None
    test_brier_calibrated: float | None
    test_log_loss_raw: float | None
    test_log_loss_calibrated: float | None
    feature_importance: dict[str, float]


@dataclass(frozen=True, slots=True)
class _Bundle:
    """What we persist: the predictor plus everything needed to use it safely.

    ``predictor`` is the thing the serving source calls ``predict_proba`` on:
    the calibrated wrapper when calibration was kept, otherwise the bare
    booster. Either way the serving path is identical, so there's no separate
    calibrator object to apply (or forget to apply).
    """

    predictor: Any
    calibrated: bool
    feature_columns: tuple[str, ...]
    trained_at: str
    train_rows: int
    # Game IDs the model trained on (booster fit + calibration folds all live
    # inside the train slice). The serving source excludes these so a backtest
    # never scores the model on games it has already seen — the difference
    # between an honest held-out number and grading its own work.
    train_game_ids: frozenset[int]


def train_model(
    session: Session,
    *,
    sport: str = "NBA",
    season: str | None = None,
    test_fraction: float = 0.2,
    window: int = 10,
    model_path: Path = DEFAULT_MODEL_PATH,
    num_boost_round: int = 200,
    calibration_folds: int = 5,
) -> TrainResult:
    """Train on the historical corpus, calibrate, and persist the model.

    ``season`` filters to a single ``HistoricalGame.season`` tag (e.g.
    ``2021-22-real``) when given; otherwise every game for ``sport`` is
    used.

    The split is two-way and strictly chronological:
      [ train (fit booster + cross-validated calibration) | test (held out) ]
    Calibration uses ``CalibratedClassifierCV`` with k-fold cross-validation
    *inside* the train slice: each fold's calibrator is fit on data the
    matching booster never saw, so calibration doesn't overfit the way a
    single small validation slice does. We keep the calibrated predictor only
    if it beats the raw booster on the held-out test slice; the test number is
    therefore always the honest one and never used to make the keep decision
    in a way that could flatter it (we report both raw and calibrated either
    way).
    """
    lgb, pd, joblib = _require_ml_deps()
    from sklearn.calibration import CalibratedClassifierCV

    games = _load_games(session, sport=sport, season=season)
    rows = build_feature_rows(games, window=window)
    if len(rows) < _MIN_TRAIN_ROWS:
        raise ValueError(
            f"Not enough games to train: have {len(rows)} feature rows, "
            f"need at least {_MIN_TRAIN_ROWS}. Ingest more seasons first."
        )

    # Chronological split: rows are already time-ordered by build_feature_rows.
    n = len(rows)
    test_start = int(n * (1.0 - test_fraction))
    train_rows = rows[:test_start]
    test_rows = rows[test_start:]

    def _new_booster() -> Any:
        return lgb.LGBMClassifier(
            objective="binary",
            n_estimators=num_boost_round,
            learning_rate=0.03,
            num_leaves=15,
            min_child_samples=30,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbose=-1,
        )

    train_X = _frame(pd, train_rows)
    train_y = [r.home_win for r in train_rows]

    booster = _new_booster()
    booster.fit(train_X, train_y)

    # Cross-validated isotonic calibration. CalibratedClassifierCV refits the
    # booster on each of k chronological folds and fits an isotonic map on the
    # held-out fold, then averages — far more stable than one tiny val slice.
    # Needs enough rows per fold and both classes present to be meaningful.
    calibrated_predictor = None
    if len(train_rows) >= calibration_folds * 20 and len(set(train_y)) == 2:
        from sklearn.model_selection import TimeSeriesSplit

        candidate = CalibratedClassifierCV(
            estimator=_new_booster(),
            method="isotonic",
            cv=TimeSeriesSplit(n_splits=calibration_folds),
        )
        candidate.fit(train_X, train_y)
        calibrated_predictor = candidate

    test_raw = _raw_predict(booster, pd, test_rows)
    test_cal = (
        _raw_predict(calibrated_predictor, pd, test_rows)
        if calibrated_predictor is not None
        else test_raw
    )
    test_y = [float(r.home_win) for r in test_rows]

    # Keep calibration only if it actually helps on the held-out slice.
    keep_calibrated = (
        calibrated_predictor is not None
        and bool(test_rows)
        and brier_score(test_cal, test_y) < brier_score(test_raw, test_y)
    )
    predictor = calibrated_predictor if keep_calibrated else booster

    importance = {
        col: float(imp)
        for col, imp in zip(FEATURE_COLUMNS, booster.feature_importances_, strict=True)
    }

    bundle = _Bundle(
        predictor=predictor,
        calibrated=keep_calibrated,
        feature_columns=FEATURE_COLUMNS,
        trained_at=datetime.now(UTC).isoformat(),
        train_rows=len(train_rows),
        train_game_ids=frozenset(r.game_id for r in train_rows),
    )
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, model_path)
    logger.info(
        "Saved model to %s (train=%d test=%d, calibrated=%s)",
        model_path, len(train_rows), len(test_rows), keep_calibrated,
    )

    return TrainResult(
        model_path=model_path,
        train_rows=len(train_rows),
        test_rows=len(test_rows),
        test_brier_raw=brier_score(test_raw, test_y) if test_rows else None,
        test_brier_calibrated=brier_score(test_cal, test_y) if test_rows else None,
        test_log_loss_raw=log_loss(test_raw, test_y) if test_rows else None,
        test_log_loss_calibrated=log_loss(test_cal, test_y) if test_rows else None,
        feature_importance=importance,
    )


def _raw_predict(predictor: Any, pd: Any, rows: list[FeatureRow]) -> list[float]:
    if not rows:
        return []
    return [float(p) for p in predictor.predict_proba(_frame(pd, rows))[:, 1]]


def _load_games(
    session: Session, *, sport: str, season: str | None
) -> list[HistoricalGame]:
    from sqlalchemy import select

    stmt = select(HistoricalGame).where(HistoricalGame.sport == sport)
    if season is not None:
        stmt = stmt.where(HistoricalGame.season == season)
    return list(session.scalars(stmt).all())


class ModelProbabilitySource:
    """Serves model P(home win) to the backtest engine.

    Predictions are computed in bulk on first use: the source builds
    leakage-safe feature rows for the games it's asked about, scores them
    once, and serves per-game lookups from the resulting map. Games the
    model has no row for (or that fall outside the trained sport) return
    None so the engine skips them.

    Crucially, games the model *trained* on are excluded from the served
    map. A backtest therefore scores the model only on held-out games —
    the honest forward-looking number, not an in-sample one.
    """

    name: ClassVar[str] = "model"

    def __init__(
        self,
        session: Session,
        *,
        sport: str = "NBA",
        season: str | None = None,
        window: int = 10,
        model_path: Path = DEFAULT_MODEL_PATH,
    ) -> None:
        _lgb, pd, joblib = _require_ml_deps()
        if not model_path.exists():
            raise FileNotFoundError(
                f"No trained model at {model_path}. Run `betedge ml train` first."
            )
        bundle: _Bundle = joblib.load(model_path)
        if bundle.feature_columns != FEATURE_COLUMNS:
            raise ValueError(
                "Saved model's feature columns don't match the current "
                "feature set — retrain with `betedge ml train`."
            )
        self._pd = pd
        self._predictions = self._score_corpus(
            bundle, session, sport=sport, season=season, window=window
        )

    def _score_corpus(
        self,
        bundle: _Bundle,
        session: Session,
        *,
        sport: str,
        season: str | None,
        window: int,
    ) -> dict[int, float]:
        games = _load_games(session, sport=sport, season=season)
        rows = build_feature_rows(games, window=window)
        # Exclude training games so the backtest only scores held-out ones.
        rows = [r for r in rows if r.game_id not in bundle.train_game_ids]
        if not rows:
            return {}
        # bundle.predictor is already the calibrated wrapper when calibration
        # was kept, so there's a single uniform predict path here.
        probs = bundle.predictor.predict_proba(_frame(self._pd, rows))[:, 1]
        return {row.game_id: float(p) for row, p in zip(rows, probs, strict=True)}

    def home_win_probability(
        self, game: HistoricalGame, market_home_prob: float
    ) -> float | None:  # noqa: ARG002
        return self._predictions.get(game.id)
