"""Unit tests for GapFadeStrategy."""

from __future__ import annotations

import sys
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from trading_engine.strategies.gap_fade import GapFadeConfig, GapFadeStrategy  # noqa: E402


class TestGapFadeConfig:
    def test_default_config_is_valid(self):
        cfg = GapFadeConfig()
        assert cfg.strategy_id == "gap_fade_v1"
        assert cfg.min_gap_bps == 60.0
        assert cfg.max_gap_bps == 300.0
        assert cfg.fade_trigger_bps == 20.0
        assert cfg.stop_loss_bps == 80.0
        assert cfg.target_mode == "vwap"

    def test_quantity_must_be_positive(self):
        with pytest.raises(ValueError, match="quantity"):
            GapFadeConfig(quantity=0)

    def test_min_gap_bps_must_be_positive(self):
        with pytest.raises(ValueError, match="min_gap_bps"):
            GapFadeConfig(min_gap_bps=0.0)

    def test_max_gap_bps_must_exceed_min_gap_bps(self):
        with pytest.raises(ValueError, match="max_gap_bps"):
            GapFadeConfig(min_gap_bps=100.0, max_gap_bps=50.0)

    def test_fade_trigger_bps_must_be_positive(self):
        with pytest.raises(ValueError, match="fade_trigger_bps"):
            GapFadeConfig(fade_trigger_bps=0.0)

    def test_stop_loss_bps_must_be_positive(self):
        with pytest.raises(ValueError, match="stop_loss_bps"):
            GapFadeConfig(stop_loss_bps=0.0)

    def test_invalid_target_mode_raises(self):
        with pytest.raises(ValueError, match="target_mode"):
            GapFadeConfig(target_mode="invalid")

    def test_target_bps_must_be_positive_when_set(self):
        with pytest.raises(ValueError, match="target_bps"):
            GapFadeConfig(target_bps=0.0)

    def test_max_trades_must_be_at_least_one(self):
        with pytest.raises(ValueError, match="max_trades_per_symbol_per_day"):
            GapFadeConfig(max_trades_per_symbol_per_day=0)

    def test_latest_entry_time_before_square_off(self):
        with pytest.raises(ValueError, match="square_off_time"):
            GapFadeConfig(
                latest_entry_time=time(15, 15),
                square_off_time=time(15, 15),
            )

    def test_valid_target_modes_accepted(self):
        for mode in ("vwap", "prior_close", "half_gap"):
            cfg = GapFadeConfig(target_mode=mode)
            assert cfg.target_mode == mode

    def test_strategy_instantiates_with_default_config(self):
        strategy = GapFadeStrategy()
        assert strategy.strategy_id == "gap_fade_v1"

    def test_on_bar_returns_empty_list_when_no_prior_close(self):
        """First day: no prior close available -> no trades."""
        from trading_engine.strategy.base import StrategyContext
        from trading_engine.strategy.signals import Bar

        strategy = GapFadeStrategy(GapFadeConfig(require_vwap_confirmation=False))
        ctx = StrategyContext(strategy_id="test", mode="backtest", config={})
        bar = Bar(
            symbol="TEST",
            exchange="NSE",
            timestamp=datetime.fromisoformat("2024-01-15 09:15:00"),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=1000,
            interval="minute",
        )
        intents = strategy.on_bar(bar, ctx)
        assert intents == []
