"""The NBA modeling pipeline: ingestion, features, and the model.

Modules:
  - ``data.py`` — real game results (nba_api) and odds (CSV / SBR XLSX).
  - ``kaggle.py`` — single-CSV ingester (games + closing moneylines).
  - ``features.py`` — leakage-safe pre-game feature engineering.
  - ``model.py`` — LightGBM training, persistence, and the
    ``ModelProbabilitySource`` that feeds the backtest engine.

Kept separate from ``backtest/seed.py`` (which generates synthetic data)
so the two stay unambiguously distinct. Seasons ingested here are
tagged with a ``-real`` suffix on ``HistoricalGame.season`` so synthetic
and real corpora can coexist in the same database.
"""
