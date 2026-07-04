"""Shared constants and utilities for paper trading scripts."""

import logging
import time

import pandas as pd
import yfinance as yf

_log = logging.getLogger(__name__)

# Only positions entered on or after this date count toward paper-trading P&L.
PAPER_TRADING_START = "2026-06-01"


def fetch_ohlcv(
    symbol: str,
    period: str = "2y",
    retries: int = 3,
    delay: float = 10.0,
) -> pd.DataFrame | None:
    """Fetch daily OHLCV data from Yahoo Finance with retries.

    yfinance uses curl_cffi (when installed) for browser-level TLS fingerprinting
    which bypasses Yahoo Finance cloud IP blocks on GitHub Actions.
    Returns a clean DataFrame with lowercase columns and timestamp index, or None on failure.
    """
    for attempt in range(1, retries + 1):
        try:
            df = yf.download(
                f"{symbol}.NS",
                period=period,
                interval="1d",
                progress=False,
                auto_adjust=True,
            )
            if df.empty:
                raise ValueError("Empty dataframe returned")
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]
            df.index.name = "timestamp"
            df = df.reset_index()
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            return df.sort_values("timestamp").reset_index(drop=True).ffill().dropna(subset=["close"])
        except Exception as exc:
            _log.warning(f"[{symbol}] Fetch attempt {attempt}/{retries} failed: {exc}")
            if attempt < retries:
                time.sleep(delay)
    return None
