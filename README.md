# BetEdge

> Full-stack sports-market analytics platform: ingest live sportsbook
> odds, de-vig them into fair probabilities, rank bets by expected
> value, and backtest strategies on both forecast quality (Brier, log
> loss, calibration) and portfolio outcomes (ROI, drawdown).
> Python 3.12 / FastAPI / Postgres backend, React 19 / TypeScript frontend.

<!-- TODO: add a screenshot or GIF of the Value Finder board here, e.g.:
     ![Value Finder](docs/screenshots/value-finder.png) -->

BetEdge is a full-stack sports-market analytics and bet-tracking
platform. It pulls live odds from US sportsbooks, computes de-vigged
market probabilities, ranks potential bets by expected value, tracks
simulated or manually recorded bankroll performance, and runs backtests
that score strategies on both **forecast quality** (Brier score, log
loss, calibration) and **portfolio outcomes** (ROI, max drawdown).

The backend is Python 3.12 + FastAPI + Postgres + SQLAlchemy 2.0 with
Alembic-managed migrations and a Click-based CLI for offline runs. The
frontend is React 19 + TypeScript + Vite, reading from the backend for
backtests, live odds, manual bet tracking, and bankroll history.

The app is designed for paper trading by default, but the tracker can
also be used as a manual journal for real wagers. It does not execute
bets, connect to sportsbooks for account actions, or move funds.
Everything is runnable locally with `docker compose up`.

## Why This Exists

Sportsbook odds are a compact, real-world probability market. BetEdge
uses that domain to demonstrate product thinking, data modeling,
frontend UX, backend API design, and quantitative engineering:

- Convert American odds into implied probabilities.
- Remove sportsbook vig to estimate fair market probability.
- Compare market consensus to the best available line.
- Track simulated or real-world wager decisions through an auditable
  bankroll ledger.
- Evaluate strategies with both statistical and portfolio metrics.

## Tech Stack

- **Frontend:** React 19, TypeScript, Vite, React Router, Recharts
- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0
- **Data:** Postgres, Alembic migrations, synthetic NBA seed corpus,
  optional real NBA/SBR ingestion
- **Quant / ML:** implied probability, de-vigging, expected value, Kelly
  sizing, Brier score, log loss, calibration, ROI, max drawdown; a
  LightGBM moneyline model with Elo-based opponent-adjusted features and
  cross-validated isotonic calibration (scikit-learn)
- **Tooling:** Docker Compose, pytest, Ruff, mypy, ESLint, TypeScript

> **Note on data**: the historical corpus shipped with the seed script
> is **synthetic** — generated from a calibrated latent-score model
> seeded at a fixed RNG state so results are reproducible. Real NBA
> data ingestion is supported via two paths documented below:
> `nba_api` for game results and SBR XLSX for closing moneylines, with
> score cross-validation between the two sources before any odds are
> written.

## Architecture

```
┌──────────────────┐     REST     ┌─────────────────────┐     SQL     ┌────────────┐
│  React 19 + TS   │ ───────────► │  FastAPI backend    │ ──────────► │ Postgres   │
│  (Vite, Recharts)│              │  SQLAlchemy 2.0     │             │ 16-alpine  │
│                  │              │  Pydantic v2        │             └────────────┘
│  /backtest  page │              │  Click CLI          │
│  /tracker       │              │                     │     HTTPS     ┌────────────┐
│  /value         │              │  Backtest engine    │ ──────────►   │ The Odds   │
│  /ai-bettor     │              │  Ranking / de-vig   │               │ API        │
│  /dashboard     │              │  Metrics: Brier,    │               └────────────┘
│                  │              │  log loss, calib.,  │
│                  │              │  ROI, drawdown      │
└──────────────────┘              └─────────────────────┘
```

### Components

**Backend (`backend/`)**
- `src/betedge/api/` — FastAPI routers: health, bets, live-odds proxy, backtest
- `src/betedge/services/` — pure business logic (de-vig, EV, Kelly, The Odds API client)
- `src/betedge/backtest/` — engine, strategies, metrics, seed generator, CLI
- `src/betedge/models.py` — SQLAlchemy 2.0 ORM models
- `src/betedge/schemas.py` — Pydantic v2 request/response schemas
- `alembic/` — versioned migrations
- `tests/` — pytest suite (87 tests, in-memory SQLite fixtures)

**Frontend (`src/`)**
- `pages/Backtest.tsx` — new page that drives the backend: run a
  strategy, see equity curve, calibration scatter, and ROI / Brier / log
  loss / drawdown, and compare the LightGBM model against the de-vigged
  market on the same held-out games
- `utils/apiClient.ts` — typed fetch wrapper for the backend
- `BetTracker`, `Dashboard`, and `Analytics` hydrate from the backend
  `/bets` API and bankroll ledger, while keeping a browser fallback so
  the UI remains usable if the backend is offline.
- `ValueFinder` calls the backend live-odds proxy so The Odds API key
  can stay in backend configuration instead of browser storage.
- `AiBettor` remains a browser-side simulation tool for now.

## Quick start (full stack)

Prerequisites: Docker Desktop + Node 20+.

```bash
cp .env.example .env
# (optional) paste your The Odds API key into ODDS_API_KEY

make dev       # Postgres + FastAPI with hot reload + auto-migrate
# in another shell:
make seed      # 400 synthetic NBA games + closing odds
make backtest  # sample market-baseline backtest
```

The frontend runs on the host against the dockerized backend:

```bash
npm install
npm run dev
# visit http://localhost:5173
```

If you do not want to use Docker, the project also supports a native
SQLite path:

```bash
make venv
make dev-native
# in another shell:
make seed-native
npm run dev
```

## Loading real historical NBA data

The synthetic corpus is fine for demos, but the forecasting model
(see Forecasting model below) needs real data to be meaningful. The
project pulls game results from the official NBA stats API and attaches
closing moneylines from a CSV (e.g. a Kaggle odds dataset) or from
SportsBookReviewsOnline (SBR) archives. Once a season is ingested, it
can be used to train and backtest the model.

### One-time setup

```bash
cd backend
pip install -e '.[ml]'   # pulls nba_api, openpyxl, lightgbm, etc.
```

### Fast path: bulk-ingest many seasons from one CSV

The public Kaggle dataset `nba_2008-2025.csv` ships game results *and*
closing odds in a single wide CSV, so one offline pass populates both
games and odds — no network calls, fully reproducible. Each season pass
writes three markets per game: the moneyline (`h2h`), the point spread
(`spreads`, signed per side), and the game total (`totals`, over/under),
so the engine can backtest moneyline *and* against-the-spread bets. This
is how the shipped model corpus (16 seasons, ~18.5k games) was built:

```bash
# Each call loads one season's games + consensus closing moneylines.
betedge data ingest-kaggle --season 2008-09 --path data/nba_2008-2025.csv
betedge data ingest-kaggle --season 2009-10 --path data/nba_2008-2025.csv
# ... through 2023-24. Re-running is idempotent (skips existing rows).
```

The nba_api + SBR path below is the alternative when you want
officially-sourced results with per-row score cross-validation.

### Ingest a season

1. Pull official game results:
   ```bash
   betedge data ingest-games --season 2023-24
   ```
   Games are tagged with `season="2023-24-real"` in the database so they
   don't collide with the synthetic corpus.

2. Download the SBR NBA moneylines XLSX for the season from
   `sportsbookreviewsonline.com/scoresoddsarchives/nba/` (manual; their
   URL pattern varies). Save it to e.g. `backend/data/nba-2023-24.xlsx`.

3. Attach odds, cross-checking the final scores against nba_api:
   ```bash
   betedge data ingest-sbr --season 2023-24 --path backend/data/nba-2023-24.xlsx
   ```
   Any row whose SBR final score disagrees with the nba_api record is
   logged and skipped — the `games_score_mismatched` counter in the
   output tells you how many. A clean season usually has 0.

4. Verify coverage:
   ```bash
   betedge data verify --season 2023-24
   ```
   Shows ingested game count, rows per book, and percent of games with
   at least one odds quote attached.

## Demo walkthrough

This is the path to show in a 2-3 minute recruiting demo:

1. **Dashboard** — start with `Load Sample Data` if the browser has no
   bets yet. The sample rows are synthetic tracked bets, included so the
   bankroll, ROI, recent-bets table, and charts are visible immediately.
2. **Value Finder** — add a free The Odds API key to backend `.env`, then
   fetch live sportsbook odds through the FastAPI proxy. The ranked board de-vigs each market,
   estimates the market's fair probability, compares that to the best
   available line, and sorts opportunities by expected value.
3. **Track a live line** — click `Track` on a Value Finder row, enter a
   stake, and the app saves that live opportunity as a pending bet
   in the Bet Tracker. The tracked bet keeps the sportsbook, odds,
   market probability, and EV context in its notes.
4. **Bet Tracker / Dashboard** — settle tracked paper bets as won, lost,
   or push. The bankroll and analytics update from the same local state.
5. **Backtest** — run a backend strategy on the synthetic NBA corpus to
   show forecast-quality metrics (Brier score, log loss, calibration)
   alongside portfolio metrics (ROI, drawdown).

Recruiter pitch:

> BetEdge is a full-stack sports-betting analytics and bet-tracking
> platform. It ingests live sportsbook odds, normalizes American odds
> into implied probabilities, removes vig to estimate market consensus,
> ranks potential bets by expected value, and lets users track simulated
> or manually recorded bets, bankroll, ROI, and backtested strategy
> performance.

## Portfolio Notes

Recommended screenshots/GIFs for a personal website:

- `Dashboard`: bankroll, ROI, recent tracked bets, and bankroll chart.
- `Value Finder`: ranked live odds board with EV and de-vig explanation.
- `Backtest`: equity curve, calibration chart, Brier score, log loss,
  ROI, and drawdown.
- `API Docs`: FastAPI Swagger page at `http://localhost:8000/docs`.

Interview talking points:

- **Product framing:** market analytics plus simulated or manually
  recorded bet tracking; the app does not place bets or move money.
- **Backend design:** typed FastAPI routers, SQLAlchemy models, Alembic
  migrations, and an append-only bankroll ledger.
- **Quant logic:** odds normalization, de-vigging, EV ranking, Kelly
  sizing, and outlier/stale line handling.
- **Testing/quality:** 87 backend tests plus Ruff, mypy, ESLint, and a
  passing frontend production build.
- **Tradeoffs:** synthetic data is reproducible for demos; real data
  ingestion exists but would need a richer feature pipeline before any
  model claims should be treated seriously.

## Backtest CLI

Installed as the `betedge` console script inside the backend container.

```bash
# One-shot market-baseline run — no bets placed, evaluates forecast
# quality (Brier / log loss / calibration) of the de-vigged market.
docker compose exec backend betedge backtest run \
    --strategy market-baseline --sport NBA

# Fractional-Kelly strategy triggered by a minimum EV threshold.
docker compose exec backend betedge backtest run \
    --strategy kelly-ev-threshold \
    --min-ev 2.0 \
    --kelly-fraction 0.25 \
    --max-stake-percent 5

# Against-the-spread instead of moneyline: settle each bet on whether the
# side covered its signed line (exact-line games push and refund the stake).
docker compose exec backend betedge backtest run \
    --strategy market-baseline --sport NBA --market spreads

# List recent runs.
docker compose exec backend betedge backtest list
```

Sample output (200-game seed, market-baseline strategy):

```json
{
  "run_id": 1,
  "strategy": "market-baseline",
  "games_evaluated": 200,
  "bets_placed": 0,
  "initial_bankroll": 1000.0,
  "final_bankroll": 1000.0,
  "roi_percent": 0.0,
  "max_drawdown": 0.0,
  "brier_score": 0.23336,
  "log_loss": 0.65859
}
```

A Brier around 0.22–0.24 for NBA moneylines matches what public research
reports for Vegas closing lines — a useful sanity check on the
synthetic generator.

## What the backend exposes

| Method | Path                           | Purpose                                  |
|--------|--------------------------------|------------------------------------------|
| GET    | `/health`                      | Liveness                                 |
| GET    | `/ready`                       | Readiness (hits DB)                      |
| GET    | `/bets`                        | List tracked bets                        |
| POST   | `/bets`                        | Add a bet; auto-computes EV / Kelly      |
| PATCH  | `/bets/{id}/status`            | Mark won / lost / push / pending         |
| DELETE | `/bets/{id}`                   | Delete + reverse bankroll impact         |
| GET    | `/bets/bankroll/snapshot`      | Current balance + full ledger            |
| GET    | `/odds/ranked?sport=NBA`       | De-vigged + ranked live odds (proxied)   |
| GET    | `/backtest/runs`               | List past runs                           |
| POST   | `/backtest/runs`               | Execute a new run, persist results       |
| GET    | `/backtest/runs/{id}`          | Run detail: metrics, calibration, equity |

Interactive docs at `http://localhost:8000/docs` once `make dev` is up.

## Tests

```bash
make test            # pytest inside the backend container
make lint            # ruff + mypy
npm run build        # tsc + vite bundle
npm run lint         # eslint
```

Current state: 87 backend tests, zero ESLint issues, zero ruff issues,
zero mypy issues, and a passing production frontend build.

GitHub Actions workflow content is included at
`docs/github-actions-ci.yml`. To enable CI, create
`.github/workflows/ci.yml` in GitHub and paste that file's contents.

## Storage layout

**Postgres** owns the canonical state when the backend is running:
`bets`, `bankroll_events`, `historical_games`, `historical_odds`,
`backtest_runs`, `backtest_bets`.

**localStorage** (browser-only): fallback/cache keys.
- `sports-betting-tracker` — cached manual bet state when the backend is unavailable
- `auto-bettor-state` — AI simulator state
- `odds-api-key` — The Odds API key for the AI simulator only. Value
  Finder uses the backend `ODDS_API_KEY` so the key does not need to be
  stored in the browser.

## Forecasting model

The platform includes a LightGBM moneyline model that plugs into the
backtest engine as an alternative probability source, so it can be
scored against the de-vigged market on identical games.

```bash
# Train on every ingested real season (chronological split, k-fold
# calibration). Omit --season to use the full multi-season corpus.
betedge ml train

# Backtest the model's predictions, scored ONLY on held-out games.
betedge backtest run --probability-source model --season 2021-22-real

# Same games, market consensus as the prediction — the bar to beat.
betedge backtest run --probability-source market --season 2021-22-real

# Point a fractional-Kelly EV strategy at the model to see ROI/drawdown.
betedge backtest run --strategy kelly-ev-threshold \
    --probability-source model --season 2021-22-real --min-ev 2
```

The same comparison is one click in the UI: the **Backtest** page has a
**Compare Model vs Market** button that runs both forecasters on the same
held-out season and renders them side by side, with the lower-Brier
forecaster highlighted as the winner.

Design notes that matter:

- **Features are strictly pre-game** (`ml/features.py`), in three groups:
  - *Form* (resets each season): rolling win% and point differential,
    season-to-date record, games played.
  - *Schedule*: rest days, rest advantage, and back-to-back flags.
  - *Opponent-adjusted strength*: an **Elo rating** carried across the
    whole corpus (regressed toward the league mean at each season
    boundary) plus the home/away Elo diff. Elo is the most important
    feature by gain — unlike win%, it credits *who* you beat.

  Every row is computed by walking games in time order and updating each
  team's state (form *and* Elo) only *after* its row is emitted, so a
  feature row never sees its own (or any future) result.
- **The split is chronological, never random** — training on the earliest
  games and evaluating on the most recent. A random split leaks future
  form into past predictions.
- **Calibration is cross-validated.** Instead of a single fragile
  validation slice, an isotonic `CalibratedClassifierCV` (k-fold
  `TimeSeriesSplit`) is fit inside the train slice, and kept only if it
  beats the raw booster on the held-out test slice. Both raw and
  calibrated metrics are always reported.
- **The backtest scores held-out games only.** The trained model records
  its training game IDs; the serving source refuses to predict those, so
  a run can't grade the model on data it already saw.

The model trains on **16 ingested NBA seasons (2008-09 .. 2023-24, ~18.5k
games)**. On the held-out **2021-22** season it lands around **Brier
0.224 / log loss 0.642**, versus **~0.209 / 0.605** for the de-vigged
closing line on the *same* games. The market still wins — as it should.
NBA closing lines are very sharp, and a model with no player, injury, or
lineup data is not expected to beat them. (Multi-season + Elo did narrow
the gap from the earlier one-season model, which sat at ~0.233.)

The ROI harness makes the consequence concrete: pointing a
fractional-Kelly EV strategy at the model's probabilities, the model
*thinks* it sees edges against the book, places ~900 bets on the
held-out season, and bleeds the bankroll down against the vig — exactly
what a slightly-worse-than-market forecaster should do. The deliverable
here is the honest, leakage-safe pipeline and the harness that proves the
comparison, not a market-beating edge.

## Future Work

The clearest remaining path to a competitive model is richer features the
public data doesn't carry — player availability/injuries, lineup and
minutes data, opponent-adjusted offensive/defensive ratings — evaluated
through the same calibration and ROI harness that already exists.

## Responsible use

This is a personal project for learning, analytics, and responsible
record keeping. Real sports betting has negative expected value against
the house take; most bettors lose money over long horizons. Nothing
here is financial advice, and the app does not place wagers or move
funds. If gambling is a problem, call 1-800-GAMBLER.
