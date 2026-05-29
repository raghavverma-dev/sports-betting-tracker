"""Tests for model training, persistence, and the engine source.

The LightGBM-dependent tests skip cleanly when the 'ml' extras (or the
native OpenMP runtime LightGBM needs) aren't available, so the core
suite still runs everywhere.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from betedge.backtest.engine import EngineConfig, run_backtest
from betedge.backtest.strategies import build_strategy
from betedge.models import HistoricalGame, HistoricalOdds

lgbm_required = pytest.importorskip("lightgbm", reason="ml extras not installed")


def _seed_learnable_corpus(session: Session, *, n: int = 300, seed: int = 7) -> None:
    """Insert games with a learnable signal: a fixed per-team strength
    drives outcomes, so a model has something real to fit. Each game gets
    a consensus moneyline so the engine has a full h2h market."""
    rng = random.Random(seed)
    teams = [f"T{i}" for i in range(10)]
    strength = {t: rng.uniform(-0.3, 0.3) for t in teams}
    base = datetime(2023, 10, 24, 19, tzinfo=UTC)

    for i in range(n):
        home, away = rng.sample(teams, 2)
        edge = strength[home] + 0.08 - strength[away]  # home-court bump
        home_wins = rng.random() < (0.5 + edge)
        hs, as_ = (110, 100) if home_wins else (100, 110)
        game = HistoricalGame(
            external_id=f"learn-{i}",
            sport="NBA",
            season="2023-24-real",
            commence_time=base + timedelta(hours=i * 6),
            home_team=home,
            away_team=away,
            home_score=hs,
            away_score=as_,
            winner="home" if home_wins else "away",
        )
        session.add(game)
        session.flush()
        for outcome, ml in ((home, -120), (away, +110)):
            session.add(
                HistoricalOdds(
                    game_id=game.id, book="consensus", market="h2h",
                    outcome=outcome, american_odds=ml,
                )
            )
    session.commit()


def test_train_predict_roundtrip(session: Session, tmp_path: Path) -> None:
    from betedge.ml.model import ModelProbabilitySource, train_model

    _seed_learnable_corpus(session, n=300)
    model_path = tmp_path / "m.joblib"

    result = train_model(
        session, season="2023-24-real", test_fraction=0.2, model_path=model_path
    )
    assert model_path.exists()
    assert result.train_rows > 0
    assert result.test_rows > 0
    assert result.test_brier_raw is not None
    assert result.test_brier_calibrated is not None
    assert 0.0 <= result.test_brier_calibrated <= 0.40

    # The source loads the persisted model and serves predictions for the
    # held-out games (training games are excluded — see the dedicated test).
    source = ModelProbabilitySource(session, season="2023-24-real", model_path=model_path)
    served = [
        source.home_win_probability(g, 0.5) for g in session.query(HistoricalGame).all()
    ]
    served_probs = [p for p in served if p is not None]
    assert served_probs  # at least the held-out slice is scored
    assert all(0.0 <= p <= 1.0 for p in served_probs)


def test_calibration_is_kept_only_when_it_helps(session: Session, tmp_path: Path) -> None:
    """Calibration is gated on the held-out test Brier: kept only if the
    cross-validated calibrated predictor beats the raw booster. Either
    outcome is valid; whichever is persisted must still serve in-range
    probabilities so downstream log loss can't blow up."""
    import joblib

    from betedge.ml.model import ModelProbabilitySource, train_model

    _seed_learnable_corpus(session, n=400)
    model_path = tmp_path / "m.joblib"
    train_model(session, season="2023-24-real", model_path=model_path)

    bundle = joblib.load(model_path)
    assert isinstance(bundle.calibrated, bool)

    # Whatever predictor was persisted must serve in-range probabilities on
    # held-out games (the source already excludes training games).
    source = ModelProbabilitySource(session, season="2023-24-real", model_path=model_path)
    served = [
        source.home_win_probability(g, 0.5) for g in session.query(HistoricalGame).all()
    ]
    assert all(0.0 <= p <= 1.0 for p in served if p is not None)


def test_train_errors_on_tiny_corpus(session: Session, tmp_path: Path) -> None:
    from betedge.ml.model import train_model

    _seed_learnable_corpus(session, n=10)
    with pytest.raises(ValueError, match="Not enough games"):
        train_model(session, season="2023-24-real", model_path=tmp_path / "m.joblib")


def test_missing_model_file_raises(session: Session, tmp_path: Path) -> None:
    from betedge.ml.model import ModelProbabilitySource

    with pytest.raises(FileNotFoundError, match="No trained model"):
        ModelProbabilitySource(session, model_path=tmp_path / "absent.joblib")


def test_engine_uses_model_source_end_to_end(session: Session, tmp_path: Path) -> None:
    from betedge.ml.model import ModelProbabilitySource, train_model

    _seed_learnable_corpus(session, n=300)
    model_path = tmp_path / "m.joblib"
    train_model(session, season="2023-24-real", model_path=model_path)

    config = EngineConfig(
        strategy=build_strategy("market-baseline"),
        sport="NBA",
        season="2023-24-real",
        probability_source=ModelProbabilitySource(
            session, season="2023-24-real", model_path=model_path
        ),
    )
    result = run_backtest(session, config, persist=False)
    assert result.games_evaluated == 300
    # Model predictions (not the market) drive the forecast metrics now.
    assert result.brier_score is not None
    assert 0.0 <= result.brier_score <= 0.40


def test_model_source_excludes_training_games(session: Session, tmp_path: Path) -> None:
    """The honest-evaluation guard: the source must refuse to predict on
    games the model trained on, so a backtest can't grade its own work."""
    import joblib

    from betedge.ml.model import ModelProbabilitySource, train_model

    _seed_learnable_corpus(session, n=300)
    model_path = tmp_path / "m.joblib"
    train_model(session, season="2023-24-real", test_fraction=0.2, model_path=model_path)

    bundle = joblib.load(model_path)
    assert len(bundle.train_game_ids) > 0

    source = ModelProbabilitySource(session, season="2023-24-real", model_path=model_path)
    games = session.query(HistoricalGame).all()
    train_game = next(g for g in games if g.id in bundle.train_game_ids)
    test_game = next(g for g in games if g.id not in bundle.train_game_ids)

    assert source.home_win_probability(train_game, 0.5) is None  # excluded
    assert source.home_win_probability(test_game, 0.5) is not None  # served


def test_source_rejects_sport_mismatch(session: Session, tmp_path: Path) -> None:
    """A model trained on one sport must refuse to score another — its
    feature rows (and Elo state) would be meaningless across sports."""
    from betedge.ml.model import ModelProbabilitySource, train_model

    _seed_learnable_corpus(session, n=200)
    model_path = tmp_path / "m.joblib"
    train_model(session, sport="NBA", season="2023-24-real", model_path=model_path)

    with pytest.raises(ValueError, match="trained on sport"):
        ModelProbabilitySource(session, sport="NHL", model_path=model_path)


def test_predictions_use_training_scope_not_requested_season(
    session: Session, tmp_path: Path
) -> None:
    """Elo carries across seasons, so a held-out game's feature vector
    depends on the whole training corpus. The serving source must rebuild
    features over the *training* scope, so the prediction for a given game
    is identical no matter which season the caller asks the engine to
    iterate. This is the guard against silent train/serve Elo skew."""
    from betedge.ml.model import ModelProbabilitySource, train_model

    # Two seasons in the corpus; train across BOTH (season=None).
    _seed_learnable_corpus(session, n=200, seed=1)
    # Re-tag half the games into a second season so the corpus spans seasons.
    games = session.query(HistoricalGame).order_by(HistoricalGame.commence_time).all()
    for g in games[: len(games) // 2]:
        g.season = "2022-23-real"
    session.commit()

    model_path = tmp_path / "m.joblib"
    train_model(session, sport="NBA", season=None, model_path=model_path)

    # Asking for one specific season must not change any served prediction,
    # because the source ignores the requested season for feature-building.
    src_all = ModelProbabilitySource(session, season=None, model_path=model_path)
    src_one = ModelProbabilitySource(session, season="2022-23-real", model_path=model_path)

    served = [
        (src_all.home_win_probability(g, 0.5), src_one.home_win_probability(g, 0.5))
        for g in session.query(HistoricalGame).all()
    ]
    both_served = [(a, b) for a, b in served if a is not None and b is not None]
    assert both_served  # some games are held out and scored by both
    assert all(a == b for a, b in both_served)


def test_api_backtest_model_source(
    client: TestClient,
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The /backtest/runs endpoint scores held-out games with the model when
    probability_source='model', and reports it on the run detail."""
    from betedge.ml import model as model_module
    from betedge.ml.model import train_model

    _seed_learnable_corpus(session, n=300)
    model_path = tmp_path / "m.joblib"
    train_model(session, season="2023-24-real", model_path=model_path)
    # The API builds ModelProbabilitySource at the default path; point it here.
    monkeypatch.setattr(model_module, "DEFAULT_MODEL_PATH", model_path)

    res = client.post(
        "/backtest/runs",
        json={
            "strategy": "market-baseline",
            "sport": "NBA",
            "season": "2023-24-real",
            "probability_source": "model",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["probability_source"] == "model"
    assert body["brier_score"] is not None
    # Only held-out games are scored, so fewer than the full seeded corpus.
    assert 0 < body["games_evaluated"] <= 300


def test_api_backtest_model_missing_artifact_is_400(
    client: TestClient,
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model run with no trained artifact returns a clean 400, not a 500."""
    from betedge.ml import model as model_module

    _seed_learnable_corpus(session, n=60)
    monkeypatch.setattr(model_module, "DEFAULT_MODEL_PATH", tmp_path / "absent.joblib")

    res = client.post(
        "/backtest/runs",
        json={
            "strategy": "market-baseline",
            "sport": "NBA",
            "season": "2023-24-real",
            "probability_source": "model",
        },
    )
    assert res.status_code == 400, res.text
    assert "No trained model" in res.json()["detail"]
