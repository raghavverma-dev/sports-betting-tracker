"""Real-data ingestion for the NBA modeling pipeline.

Currently implemented: ingestion of real game results (``data.py`` via
nba_api) and historical odds (``data.py`` CSV reader, ``sbr.py`` XLSX
reader). Feature engineering, model training, and inference are not yet
built — the trained-model strategy is the next step. The evaluation
harness it will plug into already exists in ``backtest/``.

Kept separate from ``backtest/seed.py`` (which generates synthetic data)
so the two stay unambiguously distinct. Seasons ingested here are
tagged with a ``-real`` suffix on ``HistoricalGame.season`` so synthetic
and real corpora can coexist in the same database.
"""
