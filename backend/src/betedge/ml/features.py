"""Pre-game feature engineering for the moneyline model.

The one rule that matters here is **no leakage**: every feature for a
game must be computable from information available *before tip-off*. We
enforce that structurally — games are processed in chronological order
and each team's rolling stats are updated only *after* its current
game's feature row has been emitted. A feature row therefore never sees
its own result, let alone a future game's.

Features (all from each team's prior games this season):
    home_rolling_winpct / away_rolling_winpct
        win rate over the last ``window`` games (0.5 prior when empty)
    home_rolling_margin / away_rolling_margin
        mean (points for - points against) over the last ``window`` games
    home_season_winpct / away_season_winpct
        season-to-date win rate (0.5 prior when empty)
    home_rest_days / away_rest_days
        days since the team's previous game (capped; large when first game)
    home_games_played / away_games_played
        season-to-date count (a confidence proxy for the rolling stats)

Label: ``home_win`` (1 if the home team won, else 0).

This is deliberately a compact, defensible feature set rather than an
exhaustive one — it exercises the full train/evaluate/calibrate pipeline
honestly without pretending a one-season toy model rivals a sharp
closing line.
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
)

# Cap rest so a season opener (no prior game) doesn't become an outlier.
_MAX_REST_DAYS = 14.0
_DEFAULT_WINDOW = 10


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

    def update(self, *, won: bool, margin: int, game_ordinal: int) -> None:
        self.recent_results.append(1 if won else 0)
        self.recent_margins.append(margin)
        self.season_games += 1
        self.season_wins += 1 if won else 0
        self.last_played_ordinal = game_ordinal


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

    Games are sorted by ``commence_time``. Rolling state is keyed by
    ``(season, team)`` so a team's history resets between seasons (the
    corpus may hold several ``-real`` seasons at once). Each row is built
    from state reflecting only *prior* games, then state is updated.
    """
    ordered = sorted(games, key=lambda g: (g.commence_time, g.id))
    books: dict[str, _SeasonBook] = defaultdict(_SeasonBook)
    rows: list[FeatureRow] = []

    for game in ordered:
        book = books[game.season]
        home = book._state(game.home_team, window)
        away = book._state(game.away_team, window)
        ordinal = game.commence_time.date().toordinal()

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
                    "home_rest_days": home.rest_days(ordinal),
                    "away_rest_days": away.rest_days(ordinal),
                    "home_games_played": float(home.season_games),
                    "away_games_played": float(away.season_games),
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

    return rows
