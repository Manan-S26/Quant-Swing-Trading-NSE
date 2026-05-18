"""Tests for BacktestEngine + StrategyValidator integration."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from trading_engine.backtest.cost_model import CostModel
from trading_engine.backtest.data_feed import HistoricalDataFeed
from trading_engine.backtest.engine import BacktestEngine
from trading_engine.backtest.portfolio import BacktestPortfolio
from trading_engine.backtest.simulated_broker import SimulatedBroker
from trading_engine.backtest.slippage_model import SlippageModel
from trading_engine.strategy.base import Strategy, StrategyContext
from trading_engine.strategy.signals import Bar, OrderIntent
from trading_engine.validation.models import ValidationGateConfig
from trading_engine.validation.validator import StrategyValidator

_D = Decimal
_ZERO = _D("0")


class _DoNothingStrategy(Strategy):
    def __init__(self) -> None:
        super().__init__(strategy_id="do_nothing")

    def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
        return []


def _make_df(n_bars: int = 5, price: float = 100.0) -> pd.DataFrame:
    rows = [
        {
            "timestamp": pd.Timestamp(f"2024-01-15 09:{15 + i:02d}:00"),
            "open": price,
            "high": price + 1.0,
            "low": price - 1.0,
            "close": price,
            "volume": 1000,
        }
        for i in range(n_bars)
    ]
    return pd.DataFrame(rows)


def _make_engine(
    validator: StrategyValidator | None = None,
    n_bars: int = 5,
) -> BacktestEngine:
    initial_cash = _D("100000")
    feed = HistoricalDataFeed({"RELIANCE": _make_df(n_bars)})
    portfolio = BacktestPortfolio(initial_cash=initial_cash)
    cost = CostModel(
        brokerage_per_order=_ZERO,
        brokerage_cap=_ZERO,
        stt_rate=_ZERO,
        exchange_txn_rate=_ZERO,
        sebi_rate=_ZERO,
        stamp_duty_rate=_ZERO,
        gst_rate=_ZERO,
    )
    slippage = SlippageModel(bps=_ZERO)
    broker = SimulatedBroker(portfolio=portfolio, cost_model=cost, slippage_model=slippage)
    return BacktestEngine(
        strategy=_DoNothingStrategy(),
        data_feed=feed,
        portfolio=portfolio,
        simulated_broker=broker,
        initial_cash=initial_cash,
        strategy_id="test_strategy",
        symbols=["RELIANCE"],
        strategy_validator=validator,
    )


class TestBacktestEngineValidation:
    def test_no_validator_report_has_no_validation_result(self):
        report = _make_engine().run()
        assert report.validation_result is None

    def test_with_validator_report_has_validation_result(self):
        validator = StrategyValidator(ValidationGateConfig(min_trades=0))
        report = _make_engine(validator=validator).run()
        assert report.validation_result is not None

    def test_validation_result_passes_with_zero_min_trades(self):
        validator = StrategyValidator(ValidationGateConfig(min_trades=0))
        report = _make_engine(validator=validator).run()
        assert report.validation_result.passed is True

    def test_validation_result_fails_when_min_trades_not_met(self):
        validator = StrategyValidator(ValidationGateConfig(min_trades=100))
        report = _make_engine(validator=validator).run()
        assert report.validation_result.passed is False

    def test_to_dict_includes_validation_result(self):
        validator = StrategyValidator(ValidationGateConfig(min_trades=0))
        report = _make_engine(validator=validator).run()
        d = report.to_dict()
        assert "validation_result" in d
        assert d["validation_result"]["passed"] is True

    def test_to_dict_validation_result_none_without_validator(self):
        report = _make_engine().run()
        assert report.to_dict()["validation_result"] is None

    def test_existing_engine_behavior_unchanged_without_validator(self):
        report = _make_engine().run()
        assert report.strategy_id == "test_strategy"
        assert report.metrics.trade_count == 0
        assert report.validation_result is None

    def test_validation_result_metrics_in_to_dict(self):
        validator = StrategyValidator(ValidationGateConfig(min_trades=0))
        report = _make_engine(validator=validator).run()
        vr = report.to_dict()["validation_result"]
        assert "metrics" in vr
        assert "trade_count" in vr["metrics"]
