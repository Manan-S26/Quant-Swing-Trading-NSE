"""Historical data feed for the backtesting engine.

Accepts one or more symbol DataFrames and yields bars in chronological order.
Does not mutate the original DataFrames.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

import pandas as pd

from trading_engine.strategy.signals import Bar

_REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {"timestamp", "open", "high", "low", "close", "volume"}
)


class HistoricalDataFeed:
    """Yields (timestamp, symbol, Bar) tuples in chronological order.

    Args:
        candles:       Mapping of symbol → OHLCV DataFrame.
        timestamp_col: Name of the timestamp column (default: "timestamp").
        exchange:      Exchange string embedded in each Bar (default: "NSE").
        interval:      Interval string embedded in each Bar (default: "minute").
    """

    def __init__(
        self,
        candles: dict[str, pd.DataFrame],
        timestamp_col: str = "timestamp",
        exchange: str = "NSE",
        interval: str = "minute",
    ) -> None:
        self._exchange = exchange
        self._interval = interval
        self._timestamp_col = timestamp_col
        # Validate columns and keep copies so originals are never mutated.
        self._candles: dict[str, pd.DataFrame] = {}
        for symbol, df in candles.items():
            missing = _REQUIRED_COLUMNS - set(df.columns)
            if missing:
                raise ValueError(f"DataFrame for {symbol!r} is missing required columns: {missing}")
            self._candles[symbol] = df.copy()

    def iter_bars(self) -> Iterator[tuple[datetime, str, Bar]]:
        """Yield (timestamp, symbol, Bar) in globally sorted order.

        Bars across all symbols are merged and sorted by timestamp, then by
        symbol name for a deterministic tie-breaking order.
        """
        rows: list[tuple[datetime, str, Bar]] = []

        for symbol, df in self._candles.items():
            for _, row in df.iterrows():
                ts = row[self._timestamp_col]
                if isinstance(ts, pd.Timestamp):
                    ts = ts.to_pydatetime()
                bar = Bar(
                    symbol=symbol,
                    exchange=self._exchange,
                    timestamp=ts,
                    open=Decimal(str(row["open"])),
                    high=Decimal(str(row["high"])),
                    low=Decimal(str(row["low"])),
                    close=Decimal(str(row["close"])),
                    volume=int(row["volume"]),
                    interval=self._interval,
                )
                rows.append((ts, symbol, bar))

        # Sort by timestamp then symbol for determinism.
        rows.sort(key=lambda t: (t[0], t[1]))
        yield from rows
