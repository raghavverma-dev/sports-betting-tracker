# BetEdge Demo Script

Use this for a 2-3 minute recruiter or interviewer walkthrough.

## 1. Open With The Product

BetEdge is a paper-trading and sports-market analytics platform. It does
not place real bets. It uses sportsbook odds as a probability market to
show expected value, bankroll tracking, and backtested strategy
performance.

## 2. Dashboard

Show the bankroll, ROI, recent bets, and bankroll chart. If the app has
no state yet, click `Load Sample Data` so the dashboard is populated.

What to say:

> The dashboard gives a quick portfolio view: current bankroll, total
> paper bets, win rate, net profit, ROI, and bankroll over time.

## 3. Value Finder

Open `Value Finder`, fetch live odds, and expand one row in the ranked
board.

What to say:

> This page pulls live sportsbook odds through my FastAPI backend. It
> converts American odds to implied probabilities, removes vig to get a
> fair market estimate, compares that to the best available line, and
> ranks opportunities by expected value.

Good screenshot/GIF:

- Full ranked board with a few positive-EV rows.
- Expanded row showing sportsbook-by-sportsbook odds comparison.

## 4. Track A Paper Bet

Click `Track` on a Value Finder row, enter a small paper stake, then go
to `Bet Tracker`.

What to say:

> Tracking a line writes a paper bet into the backend ledger. The bet
> keeps the sportsbook, odds, estimated market probability, and EV
> context in its notes.

## 5. Bet Tracker And Analytics

Settle one pending bet as won, lost, or push. Show the dashboard and
analytics updating.

What to say:

> The bankroll is ledger-driven: placing a bet deducts stake, settling a
> bet applies payout, and deleting a bet reverses its impact.

## 6. Backtest

Open `Backtest`, run `market-baseline`, then show the detail panel and
charts.

What to say:

> Backtesting separates forecast quality from betting performance. The
> app reports Brier score, log loss, calibration, ROI, and max drawdown,
> so strategy evaluation is not just about whether one simulated bankroll
> went up.

## Screenshot Checklist

- Dashboard overview
- Value Finder ranked board
- Expanded Value Finder row
- Bet Tracker table with pending/settled rows
- Analytics charts
- Backtest metrics and calibration chart
- FastAPI `/docs` page
