"""Paper trading market feed.

Provides a live-compatible bar iterator from pre-loaded data (list[Bar] or
DataFrame) without sleeping, without calling Zerodha, and without mutating
the input data.

Semantically intended for paper mode forward simulation, but can also be
used in tests with synthetic bars.
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


class PaperMarketFeed:
    """Yields bars in timestamp order across symbols.

    Accepts either pre-built Bar lists or OHLCV DataFrames per symbol.
    Does not sleep. Does not call Zerodha. Does not mutate input data.

    Args:
        bars:             Mapping of symbol → list[Bar] OR symbol → DataFrame.
                          DataFrames must have columns:
                          timestamp, open, high, low, close, volume.
        interval_seconds: Informational; reserved for future live-streaming
                          integration. Not used in v1 (no sleeping).
        exchange:         Exchange string embedded in Bars built from DataFrames.
        interval:         Interval label embedded in Bars built from DataFrames.
    """

    def __init__(
        self,
        bars: dict[str, list[Bar]] | dict[str, pd.DataFrame],
        interval_seconds: int | None = None,
        exchange: str = "NSE",
        interval: str = "minute",
    ) -> None:
        self._interval_seconds = interval_seconds
        self._exchange = exchange
        self._interval = interval
        # Normalise everything to list[Bar], keeping a copy so originals are safe.
        self._bars: dict[str, list[Bar]] = {}
        for symbol, data in bars.items():
            if isinstance(data, pd.DataFrame):
                self._bars[symbol] = self._df_to_bars(symbol, data.copy())
            else:
                # Shallow copy of the list (Bars are frozen dataclasses — immutable).
                self._bars[symbol] = list(data)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def iter_bars(self) -> Iterator[tuple[datetime, str, Bar]]:
        """Yield (timestamp, symbol, Bar) globally sorted by (timestamp, symbol).

        Sorting is stable and deterministic: ties on timestamp are broken by
        symbol name alphabetically.
        """
        rows: list[tuple[datetime, str, Bar]] = []
        for symbol, bar_list in self._bars.items():
            for bar in bar_list:
                rows.append((bar.timestamp, symbol, bar))
        rows.sort(key=lambda t: (t[0], t[1]))
        yield from rows

    def reset(self) -> None:
        """Reset the feed so iter_bars() can be called again from the start.

        In v1 this is a no-op because iter_bars() rebuilds the list each call.
        Provided as a seam for future stateful streaming implementations.
        """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _df_to_bars(self, symbol: str, df: pd.DataFrame) -> list[Bar]:
        missing = _REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame for {symbol!r} is missing required columns: {missing}")
        result: list[Bar] = []
        for _, row in df.iterrows():
            ts = row["timestamp"]
            if isinstance(ts, pd.Timestamp):
                ts = ts.to_pydatetime()
            result.append(
                Bar(
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
            )
        return result
