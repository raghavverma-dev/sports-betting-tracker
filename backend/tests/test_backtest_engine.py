from __future__ import annotations

from sqlalchemy.orm import Session

from betedge.backtest.engine import (
    _LOSS,
    _PUSH,
    _WIN,
    EngineConfig,
    _Quote,
    _settle,
    run_backtest,
)
from betedge.backtest.seed import SeedConfig, seed_historical_games
from betedge.backtest.strategies import build_strategy
from betedge.models import HistoricalGame


def _game(home_score: int, away_score: int) -> HistoricalGame:
    return HistoricalGame(
        external_id="settle-test",
        sport="NBA",
        season="test",
        home_team="HOME",
        away_team="AWAY",
        home_score=home_score,
        away_score=away_score,
        winner="home" if home_score > away_score else "away",
    )


def _quote(selection: str, point: float | None) -> _Quote:
    return _Quote(selection=selection, american_odds=-110, book="consensus", point=point)


def test_settle_moneyline_grades_on_winner() -> None:
    game = _game(home_score=110, away_score=100)
    # Moneyline has no line (point is None): the side wins iff its team won.
    assert _settle(_quote("HOME", None), game) == _WIN
    assert _settle(_quote("AWAY", None), game) == _LOSS


def test_settle_spread_home_favorite_covers() -> None:
    # Home favored by 4.5 (signed -4.5) and wins by 10 -> margin + line = 5.5 > 0.
    game = _game(home_score=110, away_score=100)
    assert _settle(_quote("HOME", -4.5), game) == _WIN
    # The away side carries the mirror line (+4.5); losing by 10 -> -5.5 < 0.
    assert _settle(_quote("AWAY", 4.5), game) == _LOSS


def test_settle_spread_away_dog_covers_within_the_number() -> None:
    # Home favored by 12.5 but only wins by 10: home fails to cover, dog covers.
    game = _game(home_score=110, away_score=100)
    assert _settle(_quote("HOME", -12.5), game) == _LOSS
    assert _settle(_quote("AWAY", 12.5), game) == _WIN


def test_settle_spread_exact_line_is_a_push() -> None:
    # Home favored by exactly 10 and wins by exactly 10: margin + line == 0.
    game = _game(home_score=110, away_score=100)
    assert _settle(_quote("HOME", -10.0), game) == _PUSH
    assert _settle(_quote("AWAY", 10.0), game) == _PUSH


def test_seed_then_backtest_market_baseline_reports_forecast_metrics(session: Session) -> None:
    inserted = seed_historical_games(session, SeedConfig(num_games=60, seed=7))
    assert inserted == 60

    # Running again is a no-op (idempotent by sport+season).
    assert seed_historical_games(session, SeedConfig(num_games=60, seed=7)) == 0

    config = EngineConfig(
        strategy=build_strategy("market-baseline"),
        sport="NBA",
        initial_bankroll=1000.0,
    )
    result = run_backtest(session, config)

    assert result.games_evaluated == 60
    # Baseline never bets, so bankroll is unchanged.
    assert result.bets_placed == 0
    assert result.final_bankroll == 1000.0
    assert result.roi == 0.0
    assert result.max_drawdown == 0.0
    # But the forecast-quality metrics should exist and be in plausible ranges.
    assert result.brier_score is not None
    assert 0.0 <= result.brier_score <= 0.30
    assert result.log_loss_value is not None
    assert 0.0 < result.log_loss_value < 1.0


def test_kelly_ev_strategy_places_some_bets_when_threshold_is_low(session: Session) -> None:
    seed_historical_games(session, SeedConfig(num_games=80, seed=11))

    config = EngineConfig(
        strategy=build_strategy(
            "kelly-ev-threshold",
            min_ev=0.5,
            kelly_fraction=0.25,
            max_stake_percent=5.0,
        ),
        sport="NBA",
        initial_bankroll=1000.0,
    )
    result = run_backtest(session, config)

    assert result.games_evaluated == 80
    # Because the synthetic generator adds 3.5–5% overround, true +EV
    # bets should be uncommon even in-sample — but with min_ev=0.5 and
    # 80 games we expect a handful to pass the filter.
    assert result.bets_placed >= 1
    assert result.run_id is not None
    assert result.brier_score is not None


def test_custom_probability_source_overrides_market(session: Session) -> None:
    """A non-market source replaces the prediction the engine scores —
    proving the model hook is wired through without needing LightGBM."""
    seed_historical_games(session, SeedConfig(num_games=40, seed=3))

    class AlwaysHalf:
        name = "stub"

        def home_win_probability(
            self, game: HistoricalGame, market_home_prob: float
        ) -> float | None:
            return 0.5  # deliberately uninformative

    config = EngineConfig(
        strategy=build_strategy("market-baseline"),
        sport="NBA",
        probability_source=AlwaysHalf(),
    )
    result = run_backtest(session, config, persist=False)

    # Every prediction is 0.5, so Brier = mean((0.5 - y)^2) = 0.25 exactly.
    assert result.brier_score is not None
    assert abs(result.brier_score - 0.25) < 1e-9
