"""Real-data ML pipeline: ingestion, features, training, inference.

Kept separate from `backtest/seed.py` (which generates synthetic data)
so the two stay unambiguously distinct. Seasons ingested here are
tagged with a `-real` suffix on `HistoricalGame.season` so synthetic
and real corpora can coexist in the same database.
"""
