from __future__ import annotations

from sqlalchemy.orm import Session

from betedge.backtest.engine import EngineConfig, run_backtest
from betedge.backtest.seed import SeedConfig, seed_historical_games
from betedge.backtest.strategies import build_strategy


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
