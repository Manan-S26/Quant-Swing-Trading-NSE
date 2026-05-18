"""CandleBuilder — converts live ticks into OHLCV Bar objects.

Groups incoming LiveTick objects by (symbol, interval bucket). Emits a
completed Bar whenever a tick from a new bucket arrives for that symbol.
Unconsumed open candles can be retrieved via flush().

This module has no Zerodha dependency and no network calls. It is
deterministic and fully unit-testable with synthetic ticks.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from trading_engine.live_data.models import LiveTick
from trading_engine.strategy.signals import Bar

_ZERO = Decimal("0")


@dataclass
class _OpenCandle:
    """Mutable state for a candle that has not yet been closed."""

    symbol: str
    bucket_start: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    def update(self, tick: LiveTick) -> None:
        if tick.last_price > self.high:
            self.high = tick.last_price
        if tick.last_price < self.low:
            self.low = tick.last_price
        self.close = tick.last_price
        if tick.volume is not None:
            self.volume += tick.volume

    def to_bar(self) -> Bar:
        return Bar(
            symbol=self.symbol,
            exchange="NSE",
            timestamp=self.bucket_start,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            interval="live",
        )


def _bucket_start(ts: datetime, interval_seconds: int) -> datetime:
    """Return the start of the interval bucket that contains ts.

    Works with both timezone-aware and naive datetimes. The bucket boundary
    is computed as floor(epoch_seconds / interval_seconds) * interval_seconds,
    then converted back to a datetime with the same tzinfo as the input.
    """
    tz = ts.tzinfo
    if tz is not None:
        epoch = ts.timestamp()
    else:
        # Treat naive datetimes as UTC for bucketing purposes.
        epoch = ts.replace(tzinfo=UTC).timestamp()

    bucket_epoch = math.floor(epoch / interval_seconds) * interval_seconds

    if tz is not None:
        return datetime.fromtimestamp(bucket_epoch, tz=tz)
    # For naive datetimes: compute UTC bucket then strip tzinfo to preserve naive semantics.
    return datetime.fromtimestamp(bucket_epoch, tz=UTC).replace(tzinfo=None)


class CandleBuilder:
    """Aggregates LiveTick objects into OHLCV Bar objects.

    Args:
        interval_seconds: Length of each candle in seconds. Must be > 0.
                          Defaults to 60 (1-minute candles).

    Usage:
        builder = CandleBuilder(interval_seconds=60)
        for raw_tick in feed:
            bar = builder.add_tick(raw_tick)
            if bar is not None:
                strategy.on_bar(bar, context)
        # At session end, flush any incomplete candles:
        for bar in builder.flush():
            strategy.on_bar(bar, context)
    """

    def __init__(self, interval_seconds: int = 60) -> None:
        if interval_seconds <= 0:
            raise ValueError(
                f"CandleBuilder.interval_seconds must be positive, got {interval_seconds}"
            )
        self._interval_seconds = interval_seconds
        self._open_candles: dict[str, _OpenCandle] = {}
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_tick(self, tick: LiveTick) -> Bar | None:
        """Process one tick. Returns a completed Bar if a new bucket started.

        Returns:
            A completed Bar for the *previous* bucket when the tick belongs
            to a new bucket for its symbol.  Returns None otherwise.
        """
        symbol = tick.symbol or str(tick.instrument_token)
        bucket = _bucket_start(tick.timestamp, self._interval_seconds)

        existing = self._open_candles.get(symbol)

        if existing is None:
            # First tick for this symbol — open a new candle.
            self._open_candles[symbol] = self._new_candle(symbol, bucket, tick)
            return None

        if bucket == existing.bucket_start:
            # Same bucket — update in place.
            existing.update(tick)
            return None

        # New bucket — close the old candle and start a fresh one.
        completed_bar = existing.to_bar()
        self._open_candles[symbol] = self._new_candle(symbol, bucket, tick)
        self._logger.debug(
            "Candle closed: symbol=%s bucket=%s close=%s",
            symbol,
            completed_bar.timestamp,
            completed_bar.close,
        )
        return completed_bar

    def flush(self) -> list[Bar]:
        """Return and remove all currently open (incomplete) candles as Bars.

        Call this at session end or on disconnect to avoid losing the current
        in-progress candle for each symbol.

        Returns:
            List of Bar objects (one per symbol with an open candle), in the
            order they were first seen.
        """
        bars = [candle.to_bar() for candle in self._open_candles.values()]
        self._open_candles.clear()
        return bars

    def reset(self) -> None:
        """Discard all open candles without emitting them."""
        self._open_candles.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _new_candle(symbol: str, bucket: datetime, tick: LiveTick) -> _OpenCandle:
        price = tick.last_price
        return _OpenCandle(
            symbol=symbol,
            bucket_start=bucket,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=tick.volume or 0,
        )
