"""Historical data pipeline for the trading engine.

Modules:
  universe.py    — instrument universe configuration
  validation.py  — OHLCV DataFrame validation
  historical.py  — candle downloader and Parquet storage
"""

from __future__ import annotations
