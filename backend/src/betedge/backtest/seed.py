"""Synthetic historical data generator.

WHY SYNTHETIC: closing-line data from US sportsbooks is not freely
available in a way that redistributes cleanly; scraping is brittle and
legally gray. We ship a synthetic generator so the pipeline is
reproducibly demo-able, and clearly documented so the corpus is never
mistaken for real market data. A follow-up CSV loader lets anyone plug
in their own provider (e.g. a Kaggle dataset or a paid API dump).

The generator draws team strengths from a stationary distribution,
simulates game outcomes via a latent-score model, and produces
plausible book-by-book closing lines with realistic vig (≈4%).
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from betedge.models import HistoricalGame, HistoricalOdds
from betedge.services.odds_math import probability_to_american

BOOKS = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "PointsBet", "BetRivers"]

NBA_TEAMS = [
    "Boston Celtics", "Denver Nuggets", "Milwaukee Bucks", "Phoenix Suns",
    "Los Angeles Lakers", "Los Angeles Clippers", "Golden State Warriors",
    "Dallas Mavericks", "Philadelphia 76ers", "Miami Heat",
    "Memphis Grizzlies", "New York Knicks", "Cleveland Cavaliers",
    "Brooklyn Nets", "Atlanta Hawks", "Minnesota Timberwolves",
    "Toronto Raptors", "Sacramento Kings", "Chicago Bulls", "New Orleans Pelicans",
    "Utah Jazz", "Oklahoma City Thunder", "Portland Trail Blazers",
    "Houston Rockets", "Washington Wizards", "Indiana Pacers",
    "Orlando Magic", "San Antonio Spurs", "Charlotte Hornets", "Detroit Pistons",
]


@dataclass(frozen=True, slots=True)
class SeedConfig:
    sport: str = "NBA"
    season: str = "2024-2025"
    num_games: int = 400
    start: datetime = datetime(2024, 10, 22, tzinfo=UTC)
    home_advantage: float = 0.55  # Empirical NBA home win rate sits near 0.56.
    seed: int = 42


def _generate_ratings(teams: list[str], rng: random.Random) -> dict[str, float]:
    """Draw per-team latent ratings. Mean 0, sd ~3 points (NBA-ish)."""
    return {team: rng.gauss(0, 3.0) for team in teams}


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _simulate_game(
    home: str,
    away: str,
    ratings: dict[str, float],
    home_advantage: float,
    rng: random.Random,
) -> tuple[int, int, str]:
    """Generate a final score and winner from latent strengths."""
    # Convert home-win prior to a point-spread bias, ~0.2 pts per 1% above 0.5.
    ha_points = (home_advantage - 0.5) * 20
    mu = ratings[home] - ratings[away] + ha_points

    # Score each team around a mean of 112 pts (NBA league avg) with
    # noise correlated to the latent advantage.
    home_score = max(70, int(rng.gauss(112 + mu / 2, 8)))
    away_score = max(70, int(rng.gauss(112 - mu / 2, 8)))
    if home_score == away_score:
        # Overtime tweak — +2 to one side at random to avoid ties.
        if rng.random() < 0.5:
            home_score += 2
        else:
            away_score += 2
    winner = "home" if home_score > away_score else "away"
    return home_score, away_score, winner


def _book_odds_from_true_prob(true_prob: float, vig: float, rng: random.Random) -> int:
    """Generate a book's American odds for a given true probability.

    Adds a per-book noise term (≤1.5pp) on top of the vig, so the
    backtest sees realistic line dispersion rather than every book
    agreeing exactly.
    """
    # Book posts a probability higher than true by ~vig/2 on each side.
    noisy = min(max(true_prob + rng.gauss(0, 0.01), 0.02), 0.98)
    posted = min(max(noisy + vig / 2, 0.02), 0.98)
    return probability_to_american(posted)


def seed_historical_games(
    session: Session,
    config: SeedConfig | None = None,
) -> int:
    """Populate historical_games + historical_odds. Returns number of games inserted.

    Skips if games already exist for (sport, season) — running the seed
    twice is a no-op, making it safe to call from migrations or CI.
    """
    cfg = config or SeedConfig()

    existing = (
        session.query(HistoricalGame)
        .filter_by(sport=cfg.sport, season=cfg.season)
        .count()
    )
    if existing:
        return 0

    rng = random.Random(cfg.seed)
    teams = NBA_TEAMS
    ratings = _generate_ratings(teams, rng)

    games_added = 0
    current = cfg.start
    for i in range(cfg.num_games):
        home, away = rng.sample(teams, 2)
        home_score, away_score, winner = _simulate_game(
            home, away, ratings, cfg.home_advantage, rng
        )
        external_id = _deterministic_id(cfg.season, i, home, away)

        game = HistoricalGame(
            external_id=external_id,
            sport=cfg.sport,
            season=cfg.season,
            commence_time=current,
            home_team=home,
            away_team=away,
            home_score=home_score,
            away_score=away_score,
            winner=winner,
        )
        session.add(game)
        session.flush()

        ha_points = (cfg.home_advantage - 0.5) * 20
        mu = ratings[home] - ratings[away] + ha_points
        # Map latent margin to a true home-win probability via a
        # calibrated logistic (scale 0.15 per pt is NBA-like).
        true_home_prob = _logistic(mu * 0.15)

        for book in BOOKS:
            vig = 0.035 + rng.random() * 0.015  # 3.5%–5% overround, per-book
            home_odds = _book_odds_from_true_prob(true_home_prob, vig, rng)
            away_odds = _book_odds_from_true_prob(1 - true_home_prob, vig, rng)
            session.add(
                HistoricalOdds(
                    game_id=game.id,
                    book=book,
                    market="h2h",
                    outcome=home,
                    american_odds=home_odds,
                )
            )
            session.add(
                HistoricalOdds(
                    game_id=game.id,
                    book=book,
                    market="h2h",
                    outcome=away,
                    american_odds=away_odds,
                )
            )

        games_added += 1
        # ~3 games per day on average in season.
        current += timedelta(hours=rng.randint(6, 36))

    session.commit()
    return games_added


def _deterministic_id(season: str, index: int, home: str, away: str) -> str:
    raw = f"{season}|{index}|{home}|{away}".encode()
    return hashlib.sha1(raw, usedforsecurity=False).hexdigest()[:16]
