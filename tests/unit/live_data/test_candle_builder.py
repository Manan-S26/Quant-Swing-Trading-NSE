"""Tests for live_data.candle_builder — CandleBuilder OHLCV logic."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from trading_engine.live_data.candle_builder import CandleBuilder, _bucket_start
from trading_engine.live_data.models import LiveTick
from trading_engine.strategy.signals import Bar

_TOKEN = 256265
_SYM = "RELIANCE"


def _tick(
    price: float,
    minute: int,
    second: int = 0,
    symbol: str = _SYM,
    volume: int | None = None,
) -> LiveTick:
    return LiveTick(
        instrument_token=_TOKEN,
        symbol=symbol,
        exchange=None,
        timestamp=datetime(2024, 1, 15, 9, minute, second),
        last_price=Decimal(str(price)),
        volume=volume,
    )


class TestBucketStart:
    def test_aligns_to_60s_boundary(self):
        ts = datetime(2024, 1, 15, 9, 15, 37)
        b = _bucket_start(ts, 60)
        assert b == datetime(2024, 1, 15, 9, 15, 0)

    def test_aligns_to_300s_boundary(self):
        ts = datetime(2024, 1, 15, 9, 17, 0)
        b = _bucket_start(ts, 300)
        assert b == datetime(2024, 1, 15, 9, 15, 0)

    def test_exact_boundary_unchanged(self):
        ts = datetime(2024, 1, 15, 9, 15, 0)
        b = _bucket_start(ts, 60)
        assert b == datetime(2024, 1, 15, 9, 15, 0)


class TestCandleBuilderInit:
    def test_valid_interval(self):
        b = CandleBuilder(interval_seconds=60)
        assert b._interval_seconds == 60

    def test_zero_interval_raises(self):
        with pytest.raises(ValueError, match="positive"):
            CandleBuilder(interval_seconds=0)

    def test_negative_interval_raises(self):
        with pytest.raises(ValueError, match="positive"):
            CandleBuilder(interval_seconds=-1)

    def test_default_interval_is_60(self):
        b = CandleBuilder()
        assert b._interval_seconds == 60


class TestFirstTick:
    def test_first_tick_returns_none(self):
        b = CandleBuilder()
        result = b.add_tick(_tick(100.0, 15))
        assert result is None

    def test_first_tick_stores_open(self):
        b = CandleBuilder()
        b.add_tick(_tick(100.0, 15))
        assert b._open_candles[_SYM].open == Decimal("100")

    def test_first_tick_ohlc_equal(self):
        b = CandleBuilder()
        b.add_tick(_tick(100.0, 15))
        c = b._open_candles[_SYM]
        assert c.open == c.high == c.low == c.close == Decimal("100")


class TestOHLCUpdates:
    def test_higher_price_updates_high(self):
        b = CandleBuilder()
        b.add_tick(_tick(100.0, 15, 0))
        b.add_tick(_tick(105.0, 15, 30))
        c = b._open_candles[_SYM]
        assert c.high == Decimal("105")

    def test_lower_price_updates_low(self):
        b = CandleBuilder()
        b.add_tick(_tick(100.0, 15, 0))
        b.add_tick(_tick(95.0, 15, 30))
        c = b._open_candles[_SYM]
        assert c.low == Decimal("95")

    def test_close_updates_to_latest(self):
        b = CandleBuilder()
        b.add_tick(_tick(100.0, 15, 0))
        b.add_tick(_tick(102.0, 15, 30))
        b.add_tick(_tick(101.0, 15, 50))
        c = b._open_candles[_SYM]
        assert c.close == Decimal("101")

    def test_open_never_changes(self):
        b = CandleBuilder()
        b.add_tick(_tick(100.0, 15, 0))
        b.add_tick(_tick(110.0, 15, 30))
        assert b._open_candles[_SYM].open == Decimal("100")

    def test_volume_accumulates(self):
        b = CandleBuilder()
        b.add_tick(_tick(100.0, 15, 0, volume=500))
        b.add_tick(_tick(101.0, 15, 30, volume=300))
        assert b._open_candles[_SYM].volume == 800

    def test_none_volume_does_not_add(self):
        b = CandleBuilder()
        b.add_tick(_tick(100.0, 15, 0, volume=500))
        b.add_tick(_tick(101.0, 15, 30, volume=None))
        assert b._open_candles[_SYM].volume == 500


class TestNewIntervalEmitsBar:
    def test_new_interval_returns_completed_bar(self):
        b = CandleBuilder(interval_seconds=60)
        b.add_tick(_tick(100.0, 15, 0))
        bar = b.add_tick(_tick(102.0, 16, 0))  # new minute
        assert bar is not None
        assert isinstance(bar, Bar)

    def test_completed_bar_has_correct_ohlc(self):
        b = CandleBuilder(interval_seconds=60)
        b.add_tick(_tick(100.0, 15, 0))
        b.add_tick(_tick(105.0, 15, 20))
        b.add_tick(_tick(98.0, 15, 40))
        b.add_tick(_tick(103.0, 15, 55))
        bar = b.add_tick(_tick(104.0, 16, 0))
        assert bar.open == Decimal("100")
        assert bar.high == Decimal("105")
        assert bar.low == Decimal("98")
        assert bar.close == Decimal("103")

    def test_completed_bar_symbol(self):
        b = CandleBuilder()
        b.add_tick(_tick(100.0, 15))
        bar = b.add_tick(_tick(101.0, 16))
        assert bar.symbol == _SYM

    def test_new_candle_opens_after_close(self):
        b = CandleBuilder(interval_seconds=60)
        b.add_tick(_tick(100.0, 15))
        b.add_tick(_tick(102.0, 16))  # closes 15:xx candle, opens 16:xx
        assert _SYM in b._open_candles
        assert b._open_candles[_SYM].open == Decimal("102")


class TestMultipleSymbols:
    def test_symbols_are_independent(self):
        b = CandleBuilder()
        b.add_tick(_tick(100.0, 15, symbol="RELIANCE"))
        b.add_tick(_tick(200.0, 15, symbol="INFY"))
        assert b._open_candles["RELIANCE"].open == Decimal("100")
        assert b._open_candles["INFY"].open == Decimal("200")

    def test_new_bucket_for_one_does_not_affect_other(self):
        b = CandleBuilder(interval_seconds=60)
        b.add_tick(_tick(100.0, 15, symbol="RELIANCE"))
        b.add_tick(_tick(200.0, 15, symbol="INFY"))
        bar = b.add_tick(_tick(101.0, 16, symbol="RELIANCE"))
        assert bar is not None
        assert bar.symbol == "RELIANCE"
        assert "INFY" in b._open_candles

    def test_symbol_uses_instrument_token_as_fallback(self):
        b = CandleBuilder()
        tick = LiveTick(
            instrument_token=999,
            symbol=None,
            exchange=None,
            timestamp=datetime(2024, 1, 15, 9, 15, 0),
            last_price=Decimal("50"),
        )
        b.add_tick(tick)
        assert "999" in b._open_candles


class TestFlush:
    def test_flush_returns_open_candles(self):
        b = CandleBuilder()
        b.add_tick(_tick(100.0, 15, symbol="RELIANCE"))
        b.add_tick(_tick(200.0, 15, symbol="INFY"))
        bars = b.flush()
        assert len(bars) == 2

    def test_flush_clears_state(self):
        b = CandleBuilder()
        b.add_tick(_tick(100.0, 15))
        b.flush()
        assert len(b._open_candles) == 0

    def test_flush_empty_returns_empty_list(self):
        b = CandleBuilder()
        assert b.flush() == []

    def test_flush_bars_are_bar_instances(self):
        b = CandleBuilder()
        b.add_tick(_tick(100.0, 15))
        bars = b.flush()
        assert all(isinstance(bar, Bar) for bar in bars)


class TestReset:
    def test_reset_discards_open_candles(self):
        b = CandleBuilder()
        b.add_tick(_tick(100.0, 15))
        b.reset()
        assert b._open_candles == {}

    def test_can_add_ticks_after_reset(self):
        b = CandleBuilder()
        b.add_tick(_tick(100.0, 15))
        b.reset()
        result = b.add_tick(_tick(200.0, 15))
        assert result is None
        assert _SYM in b._open_candles
