"""Pre-game feature engineering for the moneyline model.

The one rule that matters here is **no leakage**: every feature for a
game must be computable from information available *before tip-off*. We
enforce that structurally — games are processed in chronological order
and each team's state (rolling form *and* Elo rating) is updated only
*after* its current game's feature row has been emitted. A feature row
therefore never sees its own result, let alone a future game's.

Features fall into three groups:

Rolling / season form (reset each season):
    home_rolling_winpct / away_rolling_winpct
        win rate over the last ``window`` games (0.5 prior when empty)
    home_rolling_margin / away_rolling_margin
        mean (points for - points against) over the last ``window`` games
    home_season_winpct / away_season_winpct
        season-to-date win rate (0.5 prior when empty)
    home_games_played / away_games_played
        season-to-date count (a confidence proxy for the rolling stats)

Schedule / rest:
    home_rest_days / away_rest_days
        days since the team's previous game (capped; large when first game)
    rest_advantage
        home_rest_days - away_rest_days (positive = home better rested)
    home_b2b / away_b2b
        1.0 if the team played the previous calendar day, else 0.0

Opponent-adjusted strength (Elo, carried across seasons):
    home_elo / away_elo
        each team's Elo rating going into the game (1500 = league average)
    elo_diff
        home_elo - away_elo + home-court bump, the single strongest
        opponent-adjusted signal: unlike win%, it credits *who* you beat.

Why Elo persists across seasons while form resets: a team's underlying
strength carries forward (last year's contender is likely still good),
so Elo regresses toward the mean at each season boundary rather than
resetting. Recent form, by contrast, is a within-season signal and
starting it fresh each year avoids stale carryover.

Label: ``home_win`` (1 if the home team won, else 0).
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from betedge.models import HistoricalGame

FEATURE_COLUMNS: tuple[str, ...] = (
    "home_rolling_winpct",
    "away_rolling_winpct",
    "home_rolling_margin",
    "away_rolling_margin",
    "home_season_winpct",
    "away_season_winpct",
    "home_rest_days",
    "away_rest_days",
    "home_games_played",
    "away_games_played",
    "home_elo",
    "away_elo",
    "elo_diff",
    "rest_advantage",
    "home_b2b",
    "away_b2b",
)

# Cap rest so a season opener (no prior game) doesn't become an outlier.
_MAX_REST_DAYS = 14.0
_DEFAULT_WINDOW = 10

# Elo parameters. K controls how fast ratings move per game; HOME_ADV is the
# rating points added to the home side when computing the expected result
# (NBA home edge is worth roughly 100 Elo points historically). At each
# season boundary a team's rating regresses toward the league mean by
# (1 - CARRYOVER) — standard practice so strength carries forward without
# freezing last year's standings in place.
_ELO_BASE = 1500.0
_ELO_K = 20.0
_ELO_HOME_ADV = 100.0
_ELO_CARRYOVER = 0.75


@dataclass(slots=True)
class _TeamState:
    """Running, leakage-safe history for one team within one season."""

    recent_results: deque[int]  # 1 win / 0 loss, last `window` games
    recent_margins: deque[int]  # point differential, last `window` games
    season_wins: int = 0
    season_games: int = 0
    last_played_ordinal: int | None = None  # date.toordinal() of prior game

    def winpct(self) -> float:
        return sum(self.recent_results) / len(self.recent_results) if self.recent_results else 0.5

    def margin(self) -> float:
        return sum(self.recent_margins) / len(self.recent_margins) if self.recent_margins else 0.0

    def season_winpct(self) -> float:
        return self.season_wins / self.season_games if self.season_games else 0.5

    def rest_days(self, game_ordinal: int) -> float:
        if self.last_played_ordinal is None:
            return _MAX_REST_DAYS
        return min(float(game_ordinal - self.last_played_ordinal), _MAX_REST_DAYS)

    def is_b2b(self, game_ordinal: int) -> float:
        if self.last_played_ordinal is None:
            return 0.0
        return 1.0 if (game_ordinal - self.last_played_ordinal) == 1 else 0.0

    def update(self, *, won: bool, margin: int, game_ordinal: int) -> None:
        self.recent_results.append(1 if won else 0)
        self.recent_margins.append(margin)
        self.season_games += 1
        self.season_wins += 1 if won else 0
        self.last_played_ordinal = game_ordinal


@dataclass(slots=True)
class _EloBook:
    """Team Elo ratings that persist across seasons.

    Unlike ``_TeamState`` (one per season), a single ``_EloBook`` spans the
    whole corpus so a team's strength carries forward. Call ``new_season``
    at each season boundary to regress every rating toward the mean.
    """

    ratings: dict[str, float] = field(default_factory=dict)

    def rating(self, team: str) -> float:
        return self.ratings.get(team, _ELO_BASE)

    def expected_home(self, home: str, away: str) -> float:
        diff: float = (self.rating(home) + _ELO_HOME_ADV) - self.rating(away)
        return float(1.0 / (1.0 + 10.0 ** (-diff / 400.0)))

    def update(self, *, home: str, away: str, home_won: bool) -> None:
        exp_home = self.expected_home(home, away)
        actual_home = 1.0 if home_won else 0.0
        delta = _ELO_K * (actual_home - exp_home)
        self.ratings[home] = self.rating(home) + delta
        self.ratings[away] = self.rating(away) - delta

    def new_season(self) -> None:
        for team, r in self.ratings.items():
            self.ratings[team] = _ELO_BASE + _ELO_CARRYOVER * (r - _ELO_BASE)


@dataclass(slots=True)
class FeatureRow:
    game_id: int
    commence_ordinal: int
    features: dict[str, float]
    home_win: int

    def vector(self) -> list[float]:
        return [self.features[c] for c in FEATURE_COLUMNS]


@dataclass(slots=True)
class _SeasonBook:
    states: dict[str, _TeamState] = field(default_factory=dict)

    def _state(self, team: str, window: int) -> _TeamState:
        st = self.states.get(team)
        if st is None:
            st = _TeamState(
                recent_results=deque(maxlen=window),
                recent_margins=deque(maxlen=window),
            )
            self.states[team] = st
        return st


def build_feature_rows(
    games: list[HistoricalGame],
    *,
    window: int = _DEFAULT_WINDOW,
) -> list[FeatureRow]:
    """Emit one leakage-safe ``FeatureRow`` per game, in time order.

    Games are sorted by ``commence_time``. Per-season rolling state is
    keyed by ``(season, team)`` so a team's form resets between seasons.
    Elo ratings live in a single corpus-wide book and regress toward the
    mean at each season boundary. Every row is built from state reflecting
    only *prior* games; state is updated afterward.
    """
    ordered = sorted(games, key=lambda g: (g.commence_time, g.id))
    books: dict[str, _SeasonBook] = defaultdict(_SeasonBook)
    elo = _EloBook()
    rows: list[FeatureRow] = []
    prev_season: str | None = None

    for game in ordered:
        # Regress Elo toward the mean when we cross into a new season. Seasons
        # arrive in chronological order, so a change of season tag marks a
        # boundary. (No regression before the very first season.)
        if prev_season is not None and game.season != prev_season:
            elo.new_season()
        prev_season = game.season

        book = books[game.season]
        home = book._state(game.home_team, window)
        away = book._state(game.away_team, window)
        ordinal = game.commence_time.date().toordinal()

        home_elo = elo.rating(game.home_team)
        away_elo = elo.rating(game.away_team)
        home_rest = home.rest_days(ordinal)
        away_rest = away.rest_days(ordinal)

        rows.append(
            FeatureRow(
                game_id=game.id,
                commence_ordinal=ordinal,
                features={
                    "home_rolling_winpct": home.winpct(),
                    "away_rolling_winpct": away.winpct(),
                    "home_rolling_margin": home.margin(),
                    "away_rolling_margin": away.margin(),
                    "home_season_winpct": home.season_winpct(),
                    "away_season_winpct": away.season_winpct(),
                    "home_rest_days": home_rest,
                    "away_rest_days": away_rest,
                    "home_games_played": float(home.season_games),
                    "away_games_played": float(away.season_games),
                    "home_elo": home_elo,
                    "away_elo": away_elo,
                    "elo_diff": (home_elo + _ELO_HOME_ADV) - away_elo,
                    "rest_advantage": home_rest - away_rest,
                    "home_b2b": home.is_b2b(ordinal),
                    "away_b2b": away.is_b2b(ordinal),
                },
                home_win=1 if game.winner == "home" else 0,
            )
        )

        # Update *after* the row is emitted — this is what guarantees the
        # feature row never sees its own game's outcome.
        margin = game.home_score - game.away_score
        home_won = game.winner == "home"
        home.update(won=home_won, margin=margin, game_ordinal=ordinal)
        away.update(won=not home_won, margin=-margin, game_ordinal=ordinal)
        elo.update(home=game.home_team, away=game.away_team, home_won=home_won)

    return rows
