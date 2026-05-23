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
