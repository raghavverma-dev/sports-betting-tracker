from __future__ import annotations

from datetime import UTC, datetime

from betedge.services.ranking import rank_bets


def _game(
    *,
    id: str = "abc123",
    away: str = "Boston Celtics",
    home: str = "Los Angeles Lakers",
    commence: str = "2026-04-20T19:00:00Z",
    bookmakers: list[dict] | None = None,
) -> dict:
    return {
        "id": id,
        "sport_key": "basketball_nba",
        "sport_title": "NBA",
        "commence_time": commence,
        "home_team": home,
        "away_team": away,
        "bookmakers": bookmakers or [],
    }


def _h2h_book(
    title: str,
    *,
    home_price: int,
    away_price: int,
    last_update: str = "2026-04-20T18:00:00Z",
    home: str = "Los Angeles Lakers",
    away: str = "Boston Celtics",
) -> dict:
    return {
        "key": title.lower(),
        "title": title,
        "last_update": last_update,
        "markets": [
            {
                "key": "h2h",
                "outcomes": [
                    {"name": home, "price": home_price},
                    {"name": away, "price": away_price},
                ],
            }
        ],
    }


def test_rank_bets_handles_empty_games() -> None:
    assert rank_bets([]) == []


def test_best_odds_picks_highest_american_price() -> None:
    game = _game(
        bookmakers=[
            _h2h_book("DraftKings", home_price=-150, away_price=130),
            _h2h_book("FanDuel", home_price=-140, away_price=120),
            _h2h_book("BetMGM", home_price=-160, away_price=140),
        ]
    )
    bets = rank_bets([game])
    by_sel = {b.selection: b for b in bets}

    # Lakers best price is -140 (least negative = best for bettor).
    assert by_sel["Los Angeles Lakers"].best_odds == -140
    assert by_sel["Los Angeles Lakers"].best_book == "FanDuel"

    # Celtics best price is +140.
    assert by_sel["Boston Celtics"].best_odds == 140
    assert by_sel["Boston Celtics"].best_book == "BetMGM"


def test_stale_warning_fires_when_best_book_lags() -> None:
    game = _game(
        bookmakers=[
            _h2h_book(
                "DraftKings",
                home_price=-140,
                away_price=120,
                last_update="2026-04-20T17:00:00Z",  # 1h older than the rest
            ),
            _h2h_book(
                "FanDuel",
                home_price=-160,
                away_price=140,
                last_update="2026-04-20T18:00:00Z",
            ),
            _h2h_book(
                "BetMGM",
                home_price=-170,
                away_price=150,
                last_update="2026-04-20T18:00:00Z",
            ),
        ]
    )
    bets = rank_bets([game])
    by_sel = {b.selection: b for b in bets}

    # DraftKings has the best Lakers price (-140) but its quote is 60min
    # older than the freshest => STALE.
    assert by_sel["Los Angeles Lakers"].stale_warning is True
    assert by_sel["Los Angeles Lakers"].stale_minutes >= 10
    # And the engine should provide an adjusted EV using a clean book.
    assert by_sel["Los Angeles Lakers"].adjusted_ev is not None
    assert by_sel["Los Angeles Lakers"].adjusted_best_book != "DraftKings"


def test_outlier_warning_fires_when_best_book_is_far_from_consensus() -> None:
    # DraftKings' +300 on the Celtics is way better than the ~-130/+110
    # range at the other books => flagged outlier.
    game = _game(
        bookmakers=[
            _h2h_book("DraftKings", home_price=-180, away_price=300),
            _h2h_book("FanDuel", home_price=-135, away_price=115),
            _h2h_book("BetMGM", home_price=-130, away_price=110),
            _h2h_book("Caesars", home_price=-132, away_price=112),
        ]
    )
    bets = rank_bets([game])
    celtics = next(b for b in bets if b.selection == "Boston Celtics")
    assert celtics.outlier_warning is True
    assert celtics.adjusted_ev is not None


def test_ranking_sorts_by_effective_ev_descending() -> None:
    game = _game(
        bookmakers=[
            _h2h_book("DraftKings", home_price=-200, away_price=175),
            _h2h_book("FanDuel", home_price=-180, away_price=160),
            _h2h_book("BetMGM", home_price=-175, away_price=155),
        ]
    )
    bets = rank_bets([game])
    # Whichever side has higher EV must come first.
    assert bets[0].ev >= bets[-1].ev


def test_game_id_is_carried_on_every_ranked_bet() -> None:
    game = _game(id="deterministic-game-xyz", bookmakers=[
        _h2h_book("DraftKings", home_price=-150, away_price=130),
    ])
    bets = rank_bets([game])
    for b in bets:
        assert b.game_id == "deterministic-game-xyz"


def test_commence_time_parses_isoformat_with_z_suffix() -> None:
    # The Odds API uses "2026-04-20T19:00:00Z" — ensure we don't drop
    # tzinfo and that the datetime is UTC-aware.
    game = _game(
        commence="2026-04-20T19:00:00Z",
        bookmakers=[_h2h_book("DraftKings", home_price=-150, away_price=130)],
    )
    bets = rank_bets([game])
    assert bets[0].commence_time == datetime(2026, 4, 20, 19, 0, tzinfo=UTC)
