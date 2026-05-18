"""Tests for live_data.models — LiveTick validation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from trading_engine.live_data.models import LiveTick

_NOW = datetime(2024, 1, 15, 9, 30, 0)
_PRICE = Decimal("2345.00")


def _make_tick(**kwargs) -> LiveTick:
    defaults = dict(
        instrument_token=256265,
        symbol="RELIANCE",
        exchange=None,
        timestamp=_NOW,
        last_price=_PRICE,
    )
    defaults.update(kwargs)
    return LiveTick(**defaults)


class TestLiveTickValidation:
    def test_valid_tick_created(self):
        tick = _make_tick()
        assert tick.instrument_token == 256265
        assert tick.last_price == _PRICE

    def test_instrument_token_zero_raises(self):
        with pytest.raises(ValueError, match="instrument_token"):
            _make_tick(instrument_token=0)

    def test_instrument_token_negative_raises(self):
        with pytest.raises(ValueError, match="instrument_token"):
            _make_tick(instrument_token=-1)

    def test_last_price_zero_raises(self):
        with pytest.raises(ValueError, match="last_price"):
            _make_tick(last_price=Decimal("0"))

    def test_last_price_negative_raises(self):
        with pytest.raises(ValueError, match="last_price"):
            _make_tick(last_price=Decimal("-1"))

    def test_volume_none_allowed(self):
        tick = _make_tick(volume=None)
        assert tick.volume is None

    def test_volume_zero_allowed(self):
        tick = _make_tick(volume=0)
        assert tick.volume == 0

    def test_volume_positive_allowed(self):
        tick = _make_tick(volume=5000)
        assert tick.volume == 5000

    def test_volume_negative_raises(self):
        with pytest.raises(ValueError, match="volume"):
            _make_tick(volume=-1)

    def test_optional_fields_default_none(self):
        tick = _make_tick()
        assert tick.average_price is None
        assert tick.raw is None
        assert tick.volume is None

    def test_raw_dict_stored(self):
        raw = {"instrument_token": 256265, "last_price": 2345.0}
        tick = _make_tick(raw=raw)
        assert tick.raw is raw

    def test_symbol_can_be_none(self):
        tick = _make_tick(symbol=None)
        assert tick.symbol is None
