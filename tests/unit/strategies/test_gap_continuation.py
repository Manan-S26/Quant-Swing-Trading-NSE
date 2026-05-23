"""Unit tests for GapContinuationStrategy."""

from __future__ import annotations

import sys
from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from trading_engine.strategies.gap_continuation import (  # noqa: E402
    GapContinuationConfig,
    GapContinuationStrategy,
)


class TestGapContinuationConfig:
    def test_defaults_are_valid(self):
        cfg = GapContinuationConfig()
        assert cfg.strategy_id == "gap_cont_v1"
        assert cfg.min_gap_bps == 60.0
        assert cfg.max_gap_bps == 300.0
        assert cfg.continuation_trigger_bps == 20.0
        assert cfg.stop_loss_bps == 80.0
        assert cfg.target_bps is None
        assert cfg.allow_long_continuations is True
        assert cfg.allow_short_continuations is True

    def test_quantity_zero_raises(self):
        with pytest.raises(ValueError, match="quantity"):
            GapContinuationConfig(quantity=0)

    def test_min_gap_zero_raises(self):
        with pytest.raises(ValueError, match="min_gap_bps"):
            GapContinuationConfig(min_gap_bps=0.0)

    def test_max_gap_not_greater_than_min_raises(self):
        with pytest.raises(ValueError, match="max_gap_bps"):
            GapContinuationConfig(min_gap_bps=100.0, max_gap_bps=100.0)

    def test_trigger_zero_raises(self):
        with pytest.raises(ValueError, match="continuation_trigger_bps"):
            GapContinuationConfig(continuation_trigger_bps=0.0)

    def test_stop_loss_zero_raises(self):
        with pytest.raises(ValueError, match="stop_loss_bps"):
            GapContinuationConfig(stop_loss_bps=0.0)

    def test_target_bps_zero_raises(self):
        with pytest.raises(ValueError, match="target_bps"):
            GapContinuationConfig(target_bps=0.0)

    def test_target_bps_positive_valid(self):
        cfg = GapContinuationConfig(target_bps=200.0)
        assert cfg.target_bps == 200.0

    def test_square_off_after_latest_entry(self):
        with pytest.raises(ValueError, match="square_off_time"):
            GapContinuationConfig(
                latest_entry_time=time(15, 15),
                square_off_time=time(10, 30),
            )

    def test_no_fills_on_first_day(self):
        """First day has no prior close — strategy must skip all entry signals."""
        cfg = GapContinuationConfig(
            min_gap_bps=50.0,
            max_gap_bps=500.0,
            continuation_trigger_bps=10.0,
            stop_loss_bps=200.0,
            allow_long_continuations=True,
            allow_short_continuations=True,
        )
        strategy = GapContinuationStrategy(config=cfg)

        from trading_engine.strategy.signals import Bar
        bar = Bar(
            symbol="TEST",
            exchange="NSE",
            timestamp=pd.Timestamp("2024-01-15 09:20:00"),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=5000,
        )
        intents = strategy.on_bar(bar, context=None)
        assert intents == []


def _make_bar(
    symbol: str = "TEST",
    timestamp: str = "2024-01-15 09:15:00",
    open_: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.0,
    volume: int = 5000,
) -> "Bar":
    from trading_engine.strategy.signals import Bar
    return Bar(
        symbol=symbol,
        exchange="NSE",
        timestamp=pd.Timestamp(timestamp),
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=volume,
    )


def _permissive_cfg(**kwargs) -> GapContinuationConfig:
    defaults = dict(
        min_gap_bps=50.0,
        max_gap_bps=1000.0,
        continuation_trigger_bps=10.0,
        stop_loss_bps=200.0,
        target_bps=None,
        allow_long_continuations=True,
        allow_short_continuations=True,
    )
    defaults.update(kwargs)
    return GapContinuationConfig(**defaults)


class TestPriorCloseTracking:
    def test_prior_close_is_none_on_first_day(self):
        strategy = GapContinuationStrategy(config=_permissive_cfg())
        bar = _make_bar(timestamp="2024-01-15 09:15:00", close=100.0)
        strategy.on_bar(bar, context=None)
        state = strategy._states["TEST"]
        assert state.prior_close is None

    def test_prior_close_set_after_day_rollover(self):
        strategy = GapContinuationStrategy(config=_permissive_cfg())
        # Day 1: close = 107
        bar1 = _make_bar(timestamp="2024-01-15 09:15:00", close=107.0)
        strategy.on_bar(bar1, context=None)
        # Day 2: opening bar triggers reset — prior_close should be 107
        bar2 = _make_bar(timestamp="2024-01-16 09:15:00", open_=100.0, close=100.0)
        strategy.on_bar(bar2, context=None)
        state = strategy._states["TEST"]
        assert state.prior_close == Decimal("107.0")

    def test_prior_close_updates_each_day(self):
        strategy = GapContinuationStrategy(config=_permissive_cfg())
        for close_val, ts in [
            (100.0, "2024-01-15 09:15:00"),
            (110.0, "2024-01-16 09:15:00"),
            (120.0, "2024-01-17 09:15:00"),
        ]:
            bar = _make_bar(timestamp=ts, close=close_val)
            strategy.on_bar(bar, context=None)
        state = strategy._states["TEST"]
        assert state.prior_close == Decimal("110.0")
