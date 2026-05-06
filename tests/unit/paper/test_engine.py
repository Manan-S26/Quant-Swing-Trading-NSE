"""Tests for PaperTradingEngine."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from trading_engine.backtest.cost_model import CostModel
from trading_engine.backtest.slippage_model import SlippageModel
from trading_engine.domain.enums import RiskReasonCode
from trading_engine.paper.broker import PaperExecutionBroker
from trading_engine.paper.engine import PaperTradingEngine
from trading_engine.paper.market_feed import PaperMarketFeed
from trading_engine.paper.portfolio import PaperPortfolio
from trading_engine.paper.report import PaperTradingReport
from trading_engine.risk.engine import RiskEngine
from trading_engine.risk.kill_switch import KillSwitch
from trading_engine.risk.limits import RiskLimits
from trading_engine.strategy.base import Strategy, StrategyContext
from trading_engine.strategy.signals import Bar, OrderIntent

# ---------------------------------------------------------------------------
# Test strategies
# ---------------------------------------------------------------------------


class NoTradeStrategy(Strategy):
    def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
        return []


class AlwaysBuyStrategy(Strategy):
    """Buys 1 share every bar with a price to satisfy risk engine."""

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


class BuyOnceStrategy(Strategy):
    """Buys once on the first bar, then does nothing."""

    def __init__(self, strategy_id: str = "buy_once") -> None:
        super().__init__(strategy_id)
        self._bought = False

    def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
        if self._bought:
            return []
        self._bought = True
        return [
            OrderIntent(
                strategy_id=self.strategy_id,
                symbol=bar.symbol,
                exchange=bar.exchange,
                side="BUY",
                quantity=10,
                order_type="MARKET",
                product="MIS",
                price=bar.close,
            )
        ]


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
) -> PaperTradingEngine:
    portfolio = PaperPortfolio(initial_cash=initial_cash)
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
    feed = PaperMarketFeed(candles)
    broker = PaperExecutionBroker(portfolio, cost, slippage)
    return PaperTradingEngine(
        strategy=strategy,
        market_feed=feed,
        portfolio=portfolio,
        execution_broker=broker,
        strategy_id=strategy.strategy_id,
        symbols=list(candles.keys()),
        initial_cash=initial_cash,
        risk_engine=risk_engine,
    )


# ---------------------------------------------------------------------------
# Tests: basic execution
# ---------------------------------------------------------------------------


class TestBasicExecution:
    def test_runs_with_no_trade_strategy(self):
        candles = {"RELIANCE": _make_df(3)}
        engine = _make_engine(NoTradeStrategy("no_trade"), candles)
        report = engine.run()
        assert isinstance(report, PaperTradingReport)
        assert report.fills == []
        assert report.rejected_risk_decisions == []

    def test_returns_paper_trading_report(self):
        candles = {"RELIANCE": _make_df(1)}
        engine = _make_engine(NoTradeStrategy("test"), candles)
        report = engine.run()
        assert isinstance(report, PaperTradingReport)
        assert report.strategy_id == "test"
        assert report.symbols == ["RELIANCE"]

    def test_initial_and_final_cash_in_report(self):
        candles = {"RELIANCE": _make_df(1)}
        engine = _make_engine(NoTradeStrategy("test"), candles, initial_cash=Decimal("50000"))
        report = engine.run()
        assert report.initial_cash == Decimal("50000")
        assert report.final_equity == Decimal("50000")

    def test_start_and_end_time_set(self):
        candles = {"RELIANCE": _make_df(3)}
        engine = _make_engine(NoTradeStrategy("test"), candles)
        report = engine.run()
        assert report.start_time is not None
        assert report.end_time is not None
        assert report.end_time >= report.start_time


# ---------------------------------------------------------------------------
# Tests: fills recorded
# ---------------------------------------------------------------------------


class TestFillsRecorded:
    def test_fills_are_recorded(self):
        candles = {"RELIANCE": _make_df(3)}
        engine = _make_engine(AlwaysBuyStrategy("test"), candles)
        report = engine.run()
        assert len(report.fills) == 3

    def test_single_buy_fill_recorded(self):
        candles = {"RELIANCE": _make_df(3)}
        engine = _make_engine(BuyOnceStrategy(), candles)
        report = engine.run()
        assert len(report.fills) == 1
        assert report.fills[0].symbol == "RELIANCE"
        assert report.fills[0].quantity == 10

    def test_equity_curve_recorded(self):
        candles = {"RELIANCE": _make_df(3)}
        engine = _make_engine(NoTradeStrategy("test"), candles)
        report = engine.run()
        assert len(report.equity_curve) == 3


# ---------------------------------------------------------------------------
# Tests: risk engine integration
# ---------------------------------------------------------------------------


class TestRiskEngineIntegration:
    def test_no_risk_engine_approves_all(self):
        candles = {"RELIANCE": _make_df(3)}
        engine = _make_engine(AlwaysBuyStrategy("test"), candles, risk_engine=None)
        report = engine.run()
        assert len(report.fills) == 3
        assert report.rejected_risk_decisions == []

    def test_kill_switch_blocks_all_orders(self):
        ks = KillSwitch()
        ks.activate("test")
        risk_engine = RiskEngine(limits=RiskLimits(), kill_switch=ks)
        candles = {"RELIANCE": _make_df(3)}
        engine = _make_engine(AlwaysBuyStrategy("test"), candles, risk_engine=risk_engine)
        report = engine.run()
        assert len(report.fills) == 0
        assert len(report.rejected_risk_decisions) == 3
        assert all(not d.approved for d in report.rejected_risk_decisions)
        assert all(
            d.reason_code == RiskReasonCode.KILL_SWITCH_ACTIVE
            for d in report.rejected_risk_decisions
        )

    def test_rejected_risk_decisions_recorded(self):
        limits = RiskLimits(max_trades_per_day=1)
        risk_engine = RiskEngine(limits=limits)
        candles = {"RELIANCE": _make_df(3)}
        engine = _make_engine(AlwaysBuyStrategy("test"), candles, risk_engine=risk_engine)
        report = engine.run()
        assert len(report.fills) == 1
        assert len(report.rejected_risk_decisions) == 2

    def test_risk_engine_blocks_excess_order_value(self):
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


# ---------------------------------------------------------------------------
# Tests: ORB strategy on synthetic bars
# ---------------------------------------------------------------------------


class TestORBStrategy:
    def test_orb_runs_without_error(self):
        from trading_engine.strategies.orb import OpeningRangeBreakoutStrategy, ORBConfig

        # Synthetic bars for one symbol: 09:15 to 09:45 (30 bars at 1-min)
        rows = []
        for i in range(30):
            minute = 15 + i
            rows.append(
                {
                    "timestamp": pd.Timestamp(f"2024-01-15 09:{minute:02d}:00"),
                    "open": 100.0,
                    "high": 100.0 + i * 0.5,
                    "low": 100.0 - 0.5,
                    "close": 100.0 + i * 0.2,
                    "volume": 1000,
                }
            )
        df = pd.DataFrame(rows)
        candles = {"RELIANCE": df}

        config = ORBConfig(opening_range_minutes=5)
        strategy = OpeningRangeBreakoutStrategy(config=config)

        engine = _make_engine(strategy, candles)
        report = engine.run()
        assert isinstance(report, PaperTradingReport)
        assert report.strategy_id == "orb_v1"
        # No assertion on fills — just verifying no crash

    def test_orb_does_not_call_zerodha(self):
        """Verify no Zerodha SDK is imported in paper/engine.py."""
        import trading_engine.paper.engine as mod

        source = mod.__file__
        with open(source) as f:
            lines = f.readlines()
        import_lines = [ln for ln in lines if ln.strip().startswith(("import ", "from "))]
        assert not any("zerodha" in ln.lower() for ln in import_lines)
        assert not any("kiteconnect" in ln.lower() for ln in import_lines)


# ---------------------------------------------------------------------------
# Tests: empty feed
# ---------------------------------------------------------------------------


class TestEmptyFeed:
    def test_empty_feed_produces_valid_report(self):
        engine = _make_engine(NoTradeStrategy("test"), {})
        report = engine.run()
        assert report.fills == []
        assert report.start_time is None
        assert report.end_time is None
        assert report.final_equity == Decimal("100000")


# ---------------------------------------------------------------------------
# Tests: no Zerodha imports
# ---------------------------------------------------------------------------


class TestNoZerodhImports:
    def test_paper_package_has_no_zerodha_imports(self):
        import importlib

        paper_modules = [
            "trading_engine.paper.engine",
            "trading_engine.paper.broker",
            "trading_engine.paper.portfolio",
            "trading_engine.paper.market_feed",
            "trading_engine.paper.report",
        ]
        for mod_name in paper_modules:
            mod = importlib.import_module(mod_name)
            src = mod.__file__
            with open(src) as f:
                lines = f.readlines()
            import_lines = [ln for ln in lines if ln.strip().startswith(("import ", "from "))]
            assert not any("zerodha" in ln.lower() for ln in import_lines), (
                f"{mod_name} has a zerodha import"
            )
            assert not any("kiteconnect" in ln.lower() for ln in import_lines), (
                f"{mod_name} has a kiteconnect import"
            )
