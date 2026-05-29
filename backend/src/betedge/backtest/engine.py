"""The backtest engine.

Walks historical games in time order, computes the market-consensus
probability from de-vigged closing odds, lets the chosen strategy
decide whether/how to bet, and records the resulting equity curve plus
forecast-quality metrics.

This is deliberately a simple event loop with no vectorization — easy
to read and correct to within floating-point error, which matters more
than speed at the volumes we're working with. Parallelization can be
layered on later (e.g. with Dask or multiprocessing per-sport) once we
care about 10x the game count.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from betedge.backtest.metrics import (
    brier_score,
    calibration_curve,
    log_loss,
    max_drawdown,
    roi,
)
from betedge.backtest.strategies import BetDecision, GameQuote, Strategy
from betedge.models import (
    BacktestBet,
    BacktestRun,
    HistoricalGame,
    HistoricalOdds,
)
from betedge.services.odds_math import implied_probability

logger = logging.getLogger(__name__)


class ProbabilitySource(Protocol):
    """Supplies the probability a strategy treats as its own forecast.

    The engine always de-vigs the market separately (for the EV decision
    and the calibration curve); this hook decides what the *prediction*
    is. The market source echoes the de-vigged market back, so
    market-baseline scores the market against reality. A model source
    ignores ``market_home_prob`` and returns a learned P(home win) that
    can disagree with the market — which is the whole point of a model.
    """

    @property
    def name(self) -> str:
        """Short identifier recorded on the run (e.g. 'market', 'model')."""
        ...

    def home_win_probability(
        self, game: HistoricalGame, market_home_prob: float
    ) -> float | None:
        """Return P(home win) in [0, 1], or None to skip this game."""
        ...


class MarketProbabilitySource:
    """Default source: the prediction *is* the de-vigged market price."""

    name: ClassVar[str] = "market"

    def home_win_probability(
        self, game: HistoricalGame, market_home_prob: float
    ) -> float | None:  # noqa: ARG002
        return market_home_prob


@dataclass(frozen=True, slots=True)
class _Quote:
    """One settled-against book quote for a side of a game.

    ``point`` is the signed spread line for that selection (negative when
    the side is favored), or None for moneyline (h2h) markets.
    """

    selection: str
    american_odds: int
    book: str
    point: float | None


@dataclass(frozen=True, slots=True)
class EngineConfig:
    strategy: Strategy
    sport: str
    market: str = "h2h"
    season: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    initial_bankroll: float = 1000.0
    probability_source: ProbabilitySource = field(default_factory=MarketProbabilitySource)


@dataclass(slots=True)
class EngineResult:
    run_id: int | None
    games_evaluated: int
    bets_placed: int
    final_bankroll: float
    roi: float
    max_drawdown: float
    brier_score: float | None
    log_loss_value: float | None
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)


def _query_games(session: Session, config: EngineConfig) -> list[HistoricalGame]:
    stmt = (
        select(HistoricalGame)
        .options(selectinload(HistoricalGame.odds))
        .where(HistoricalGame.sport == config.sport)
        .order_by(HistoricalGame.commence_time.asc())
    )
    if config.season is not None:
        stmt = stmt.where(HistoricalGame.season == config.season)
    if config.start_date is not None:
        stmt = stmt.where(HistoricalGame.commence_time >= config.start_date)
    if config.end_date is not None:
        stmt = stmt.where(HistoricalGame.commence_time <= config.end_date)
    return list(session.scalars(stmt).all())


def _best_quotes_per_side(
    odds_rows: list[HistoricalOdds],
    game: HistoricalGame,
    market: str,
) -> tuple[_Quote | None, _Quote | None]:
    """Return (home_best, away_best) quotes, or None for a side with no
    quote in `market`.

    "Best" = highest (most-favorable-to-bettor) American odds. Per the
    earlier ranking.py analysis, arithmetic max is the correct ordering
    for American odds. For spreads, every row carries its signed ``point``
    (the line from that side's perspective) so settlement can judge a cover.
    """
    market_rows = [r for r in odds_rows if r.market == market]
    home_rows = [r for r in market_rows if r.outcome == game.home_team]
    away_rows = [r for r in market_rows if r.outcome == game.away_team]

    def _best(rows: list[HistoricalOdds]) -> _Quote | None:
        if not rows:
            return None
        top = max(rows, key=lambda r: r.american_odds)
        return _Quote(top.outcome, top.american_odds, top.book, top.point)

    return _best(home_rows), _best(away_rows)


def _devigged_market_probability(
    odds_rows: list[HistoricalOdds],
    game: HistoricalGame,
    market: str,
    *,
    target: str,
) -> float | None:
    """Market consensus probability for `target` (the team name)
    obtained by de-vigging each book and averaging.
    """
    market_rows = [r for r in odds_rows if r.market == market]
    by_book: dict[str, list[HistoricalOdds]] = {}
    for r in market_rows:
        by_book.setdefault(r.book, []).append(r)

    fair_probs: list[float] = []
    for rows in by_book.values():
        overround = sum(implied_probability(r.american_odds) for r in rows)
        if overround <= 0:
            continue
        for r in rows:
            if r.outcome == target:
                fair_probs.append(implied_probability(r.american_odds) / overround)

    if not fair_probs:
        return None
    return sum(fair_probs) / len(fair_probs)


def run_backtest(
    session: Session,
    config: EngineConfig,
    *,
    persist: bool = True,
) -> EngineResult:
    """Execute a backtest and optionally persist the run + bets to the DB."""
    games = _query_games(session, config)

    fallback_ts = datetime.now(UTC)
    start_ts = config.start_date or (games[0].commence_time if games else fallback_ts)
    end_ts = config.end_date or (games[-1].commence_time if games else fallback_ts)

    run: BacktestRun | None = None
    if persist:
        params = {"initial_bankroll": config.initial_bankroll}
        run = BacktestRun(
            strategy=config.strategy.name,
            sport=config.sport,
            market=config.market,
            start_date=start_ts,
            end_date=end_ts,
            params_json=json.dumps(params),
            initial_bankroll=config.initial_bankroll,
        )
        session.add(run)
        session.flush()  # Assigns run.id without committing.

    bankroll = config.initial_bankroll
    equity_curve: list[tuple[datetime, float]] = [(start_ts, bankroll)]
    predictions: list[float] = []
    outcomes: list[float] = []
    placed = 0

    is_h2h = config.market == "h2h"

    for game in games:
        home_best, away_best = _best_quotes_per_side(game.odds, game, config.market)
        if not (home_best and away_best):
            continue  # Skip games without a full market in the corpus.

        market_home_prob = _devigged_market_probability(
            game.odds, game, config.market, target=game.home_team
        )
        if market_home_prob is None:
            continue
        market_away_prob = 1.0 - market_home_prob  # complement after de-vig

        # The prediction (what the strategy bets on) comes from the configured
        # source. For h2h the source's P(home win) is directly the home
        # selection's win probability; for spreads/totals the model has no
        # cover forecast, so we fall back to the de-vigged market price (the
        # backtest then measures the betting mechanics and cover rate, not a
        # model edge that doesn't exist for these markets yet).
        if is_h2h:
            pred_home = config.probability_source.home_win_probability(game, market_home_prob)
            if pred_home is None:
                continue
            pred_home = min(max(pred_home, 0.0), 1.0)
        else:
            pred_home = market_home_prob
        pred_away = 1.0 - pred_home

        # Forecast-quality metrics are only meaningful for h2h, where the
        # prediction is P(team wins) and the outcome is the realized win.
        # Spread/total cover probabilities aren't comparable, so we don't
        # pollute Brier/log loss with them.
        if is_h2h:
            home_win = 1.0 if game.winner == "home" else 0.0
            away_win = 1.0 if game.winner == "away" else 0.0
            predictions.extend([pred_home, pred_away])
            outcomes.extend([home_win, away_win])

        decision, realized = _evaluate_strategy(
            config.strategy,
            game,
            home_best,
            away_best,
            pred_home,
            pred_away,
            market_home_prob,
            market_away_prob,
            bankroll,
        )
        if decision is None:
            continue

        bankroll = round(bankroll - decision.stake + realized.payout, 2)
        placed += 1
        equity_curve.append((game.commence_time, bankroll))

        if run is not None:
            session.add(
                BacktestBet(
                    run_id=run.id,
                    game_id=game.id,
                    selection=decision.selection,
                    american_odds=decision.american_odds,
                    book=decision.book,
                    predicted_probability=decision.predicted_probability,
                    market_probability=decision.market_probability,
                    stake=decision.stake,
                    payout=realized.payout,
                    outcome=realized.outcome_value,
                    bankroll_after=bankroll,
                )
            )

    brier = brier_score(predictions, outcomes) if predictions else None
    ll = log_loss(predictions, outcomes) if predictions else None
    calibration = calibration_curve(predictions, outcomes) if predictions else []
    curve_values = [b for _, b in equity_curve]
    dd = max_drawdown(curve_values)
    ret = roi(config.initial_bankroll, bankroll)

    result = EngineResult(
        run_id=run.id if run else None,
        games_evaluated=len(games),
        bets_placed=placed,
        final_bankroll=bankroll,
        roi=ret,
        max_drawdown=dd,
        brier_score=brier,
        log_loss_value=ll,
        equity_curve=equity_curve,
    )

    if run is not None:
        run.games_evaluated = result.games_evaluated
        run.bets_placed = result.bets_placed
        run.brier_score = brier
        run.log_loss = ll
        run.calibration_json = json.dumps(
            [
                {
                    "bin_lower": c.bin_lower,
                    "bin_upper": c.bin_upper,
                    "predicted_mean": c.predicted_mean,
                    "empirical_mean": None if c.count == 0 else c.empirical_mean,
                    "count": c.count,
                }
                for c in calibration
            ]
        )
        run.final_bankroll = bankroll
        run.roi = ret
        run.max_drawdown = dd
        run.finished_at = datetime.now(UTC)
        session.commit()

    return result


@dataclass(frozen=True, slots=True)
class _Realized:
    payout: float
    outcome_value: float  # 1 = win, 0 = loss, 0.5 = push


def _evaluate_strategy(
    strategy: Strategy,
    game: HistoricalGame,
    home_best: _Quote,
    away_best: _Quote,
    pred_home: float,
    pred_away: float,
    market_home: float,
    market_away: float,
    bankroll: float,
) -> tuple[BetDecision | None, _Realized]:
    """Ask the strategy to consider each side and return the chosen bet.

    We give the strategy both sides in sequence; if it picks the first
    we don't consider the second (one bet per game for now). This keeps
    the bet-placement logic simple and mirrors how the live AiBettor
    already behaves via the `usedGameIds` block.
    """
    for quote_q, predicted, market in (
        (home_best, pred_home, market_home),
        (away_best, pred_away, market_away),
    ):
        quote = GameQuote(
            game_id=game.id,
            selection=quote_q.selection,
            american_odds=quote_q.american_odds,
            book=quote_q.book,
            market_probability=market,
            predicted_probability=predicted,
        )
        decision = strategy.decide(quote, bankroll)
        if decision is None:
            continue

        result = _settle(quote_q, game)
        if result == _PUSH:
            # Stake refunded: net zero. Record as a 0.5 outcome (neither win
            # nor loss) so accuracy stats don't count a push either way.
            realized = _Realized(payout=decision.stake, outcome_value=0.5)
        else:
            won = result == _WIN
            realized = _Realized(
                payout=decision.potential_payout if won else 0.0,
                outcome_value=1.0 if won else 0.0,
            )
        return decision, realized

    return None, _Realized(payout=0.0, outcome_value=0.0)


_WIN, _LOSS, _PUSH = 1, 0, -1


def _settle(quote: _Quote, game: HistoricalGame) -> int:
    """Grade a bet on ``quote.selection``: _WIN / _LOSS / _PUSH.

    Moneyline (``point is None``): the side wins iff its team won.
    Spread (signed ``point``): the side covers iff its scoring margin plus
    its line is positive; exactly zero is a push (stake refunded).
    """
    is_home = quote.selection == game.home_team
    margin = (game.home_score - game.away_score) if is_home else (
        game.away_score - game.home_score
    )

    if quote.point is None:  # moneyline
        return _WIN if margin > 0 else _LOSS

    ats = margin + quote.point
    if ats > 0:
        return _WIN
    if ats < 0:
        return _LOSS
    return _PUSH
