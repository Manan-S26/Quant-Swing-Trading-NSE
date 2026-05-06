"""Tests for BacktestEngine integration with RiskEngine."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from trading_engine.backtest.cost_model import CostModel
from trading_engine.backtest.data_feed import HistoricalDataFeed
from trading_engine.backtest.engine import BacktestEngine
from trading_engine.backtest.portfolio import BacktestPortfolio
from trading_engine.backtest.simulated_broker import SimulatedBroker
from trading_engine.backtest.slippage_model import SlippageModel
from trading_engine.domain.enums import RiskReasonCode
from trading_engine.risk.engine import RiskEngine
from trading_engine.risk.kill_switch import KillSwitch
from trading_engine.risk.limits import RiskLimits
from trading_engine.strategy.base import Strategy, StrategyContext
from trading_engine.strategy.signals import Bar, OrderIntent

# ---------------------------------------------------------------------------
# Minimal test strategies
# ---------------------------------------------------------------------------


class AlwaysBuyStrategy(Strategy):
    """Emits a BUY MARKET intent on every bar (price = bar close)."""

    def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
        return [
            OrderIntent(
                strategy_id=self.strategy_id,
                symbol=bar.symbol,
                exchange=bar.exchange,
                side="BUY",
                quantity=1,
                order_type="MARKET",
                product="MIS",
                price=bar.close,
            )
        ]


class NoTradeStrategy(Strategy):
    def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_df(n_bars: int = 3, price: float = 100.0) -> pd.DataFrame:
    rows = [
        {
            "timestamp": pd.Timestamp(f"2024-01-15 09:{30 + i:02d}:00"),
            "open": price,
            "high": price + 5,
            "low": price - 5,
            "close": price,
            "volume": 1000,
        }
        for i in range(n_bars)
    ]
    return pd.DataFrame(rows)


def _make_engine(
    strategy: Strategy,
    candles: dict[str, pd.DataFrame],
    risk_engine: RiskEngine | None = None,
    initial_cash: Decimal = Decimal("100000"),
) -> BacktestEngine:
    portfolio = BacktestPortfolio(initial_cash=initial_cash)
    cost = CostModel(
        brokerage_per_order=Decimal("0"),
        brokerage_cap=Decimal("0"),
        stt_rate=Decimal("0"),
        exchange_txn_rate=Decimal("0"),
        sebi_rate=Decimal("0"),
        stamp_duty_rate=Decimal("0"),
        gst_rate=Decimal("0"),
    )
    slippage = SlippageModel(bps=Decimal("0"))
    feed = HistoricalDataFeed(candles)
    broker = SimulatedBroker(portfolio, cost, slippage)
    return BacktestEngine(
        strategy=strategy,
        data_feed=feed,
        portfolio=portfolio,
        simulated_broker=broker,
        initial_cash=initial_cash,
        strategy_id=strategy.strategy_id,
        symbols=list(candles.keys()),
        risk_engine=risk_engine,
    )


# ---------------------------------------------------------------------------
# Tests: no risk engine (backward compat)
# ---------------------------------------------------------------------------


class TestNoRiskEngine:
    def test_no_risk_engine_approves_all(self):
        candles = {"RELIANCE": _make_df(3)}
        engine = _make_engine(AlwaysBuyStrategy("test"), candles, risk_engine=None)
        report = engine.run()
        assert len(report.fills) == 3
        assert len(report.rejected_risk_decisions) == 0

    def test_report_has_empty_rejected_decisions_by_default(self):
        candles = {"RELIANCE": _make_df(2)}
        engine = _make_engine(NoTradeStrategy("no_trade"), candles, risk_engine=None)
        report = engine.run()
        assert report.rejected_risk_decisions == []


# ---------------------------------------------------------------------------
# Tests: kill switch blocks all orders
# ---------------------------------------------------------------------------


class TestKillSwitchIntegration:
    def test_active_kill_switch_blocks_all_fills(self):
        ks = KillSwitch()
        ks.activate("emergency stop")
        risk_engine = RiskEngine(limits=RiskLimits(), kill_switch=ks)
        candles = {"RELIANCE": _make_df(3)}
        engine = _make_engine(AlwaysBuyStrategy("test"), candles, risk_engine=risk_engine)
        report = engine.run()
        assert len(report.fills) == 0
        assert len(report.rejected_risk_decisions) == 3
        assert all(
            d.reason_code == RiskReasonCode.KILL_SWITCH_ACTIVE
            for d in report.rejected_risk_decisions
        )

    def test_rejected_decisions_not_approved(self):
        ks = KillSwitch()
        ks.activate("test")
        risk_engine = RiskEngine(limits=RiskLimits(), kill_switch=ks)
        candles = {"RELIANCE": _make_df(1)}
        engine = _make_engine(AlwaysBuyStrategy("test"), candles, risk_engine=risk_engine)
        report = engine.run()
        assert all(not d.approved for d in report.rejected_risk_decisions)


# ---------------------------------------------------------------------------
# Tests: order value limit
# ---------------------------------------------------------------------------


class TestOrderValueLimit:
    def test_order_value_exceeding_limit_is_rejected(self):
        # price=100, qty=1 → value=100; limit=50 → rejected
        limits = RiskLimits(max_order_value=Decimal("50"))
        risk_engine = RiskEngine(limits=limits)
        candles = {"RELIANCE": _make_df(1, price=100.0)}
        engine = _make_engine(AlwaysBuyStrategy("test"), candles, risk_engine=risk_engine)
        report = engine.run()
        assert len(report.fills) == 0
        assert len(report.rejected_risk_decisions) == 1
        assert (
            report.rejected_risk_decisions[0].reason_code
            == RiskReasonCode.ORDER_VALUE_LIMIT_BREACHED
        )

    def test_order_within_value_limit_is_approved(self):
        limits = RiskLimits(max_order_value=Decimal("500"))
        risk_engine = RiskEngine(limits=limits)
        candles = {"RELIANCE": _make_df(1, price=100.0)}
        engine = _make_engine(AlwaysBuyStrategy("test"), candles, risk_engine=risk_engine)
        report = engine.run()
        assert len(report.fills) == 1


# ---------------------------------------------------------------------------
# Tests: trade count limit
# ---------------------------------------------------------------------------


class TestTradeCountLimit:
    def test_trades_per_day_limit_blocks_excess(self):
        limits = RiskLimits(max_trades_per_day=2)
        risk_engine = RiskEngine(limits=limits)
        candles = {"RELIANCE": _make_df(5)}
        engine = _make_engine(AlwaysBuyStrategy("test"), candles, risk_engine=risk_engine)
        report = engine.run()
        assert len(report.fills) == 2
        assert len(report.rejected_risk_decisions) == 3


# ---------------------------------------------------------------------------
# Tests: report serialisation includes rejected decisions
# ---------------------------------------------------------------------------


class TestReportSerialisation:
    def test_to_dict_includes_rejected_decisions(self):
        ks = KillSwitch()
        ks.activate("test")
        risk_engine = RiskEngine(limits=RiskLimits(), kill_switch=ks)
        candles = {"RELIANCE": _make_df(1)}
        engine = _make_engine(AlwaysBuyStrategy("test"), candles, risk_engine=risk_engine)
        report = engine.run()
        d = report.to_dict()
        assert "rejected_risk_decisions" in d
        assert len(d["rejected_risk_decisions"]) == 1
        entry = d["rejected_risk_decisions"][0]
        assert entry["approved"] is False
        assert "risk_decision_id" in entry
        assert "reason_code" in entry
        assert "timestamp" in entry

    def test_to_dict_empty_rejected_when_no_risk_engine(self):
        candles = {"RELIANCE": _make_df(1)}
        engine = _make_engine(AlwaysBuyStrategy("test"), candles, risk_engine=None)
        report = engine.run()
        d = report.to_dict()
        assert d["rejected_risk_decisions"] == []

    def test_save_json_includes_rejected_decisions(self, tmp_path):
        import json

        ks = KillSwitch()
        ks.activate("test")
        risk_engine = RiskEngine(limits=RiskLimits(), kill_switch=ks)
        candles = {"RELIANCE": _make_df(1)}
        engine = _make_engine(AlwaysBuyStrategy("test"), candles, risk_engine=risk_engine)
        report = engine.run()
        path = tmp_path / "report.json"
        report.save_json(path)
        with open(path) as f:
            data = json.load(f)
        assert "rejected_risk_decisions" in data
        assert len(data["rejected_risk_decisions"]) == 1
