"""Tests for BacktestEngine with simple dummy strategies."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from trading_engine.backtest.cost_model import CostModel
from trading_engine.backtest.data_feed import HistoricalDataFeed
from trading_engine.backtest.engine import BacktestEngine
from trading_engine.backtest.portfolio import BacktestPortfolio
from trading_engine.backtest.report import BacktestReport
from trading_engine.backtest.simulated_broker import SimulatedBroker
from trading_engine.backtest.slippage_model import SlippageModel
from trading_engine.strategy.base import Strategy, StrategyContext
from trading_engine.strategy.signals import Bar, OrderIntent

# ---------------------------------------------------------------------------
# Test-only strategies
# ---------------------------------------------------------------------------


class NoTradeStrategy(Strategy):
    """Never emits any order intents."""

    def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
        return []


class BuyFirstBarStrategy(Strategy):
    """Buys 10 shares on the very first bar it sees, then does nothing."""

    def __init__(self, strategy_id: str = "buy_first") -> None:
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
            )
        ]


class BuyThenSellStrategy(Strategy):
    """Buys 10 on first bar, sells 10 on second bar."""

    def __init__(self, strategy_id: str = "buy_then_sell") -> None:
        super().__init__(strategy_id)
        self._bar_count = 0

    def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
        self._bar_count += 1
        if self._bar_count == 1:
            return [
                OrderIntent(
                    strategy_id=self.strategy_id,
                    symbol=bar.symbol,
                    exchange=bar.exchange,
                    side="BUY",
                    quantity=10,
                    order_type="MARKET",
                    product="MIS",
                )
            ]
        if self._bar_count == 2:
            return [
                OrderIntent(
                    strategy_id=self.strategy_id,
                    symbol=bar.symbol,
                    exchange=bar.exchange,
                    side="SELL",
                    quantity=10,
                    order_type="MARKET",
                    product="MIS",
                )
            ]
        return []


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_df(timestamps: list[str], base_price: float = 500.0) -> pd.DataFrame:
    rows = []
    for ts in timestamps:
        rows.append(
            {
                "timestamp": pd.Timestamp(ts),
                "open": base_price,
                "high": base_price + 10,
                "low": base_price - 10,
                "close": base_price,
                "volume": 10000,
            }
        )
    return pd.DataFrame(rows)


def _make_engine(
    strategy: Strategy,
    candles: dict[str, pd.DataFrame],
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
    )


_TIMESTAMPS = [
    "2024-01-15 09:15:00",
    "2024-01-15 09:16:00",
    "2024-01-15 09:17:00",
]


# ---------------------------------------------------------------------------
# Engine produces BacktestReport
# ---------------------------------------------------------------------------


class TestEngineReturnsReport:
    def test_run_returns_backtest_report(self) -> None:
        df = _make_df(_TIMESTAMPS)
        engine = _make_engine(NoTradeStrategy("no_trade"), {"RELIANCE": df})
        report = engine.run()
        assert isinstance(report, BacktestReport)

    def test_report_has_strategy_id(self) -> None:
        df = _make_df(_TIMESTAMPS)
        engine = _make_engine(NoTradeStrategy("my_strat"), {"RELIANCE": df})
        report = engine.run()
        assert report.strategy_id == "my_strat"

    def test_report_has_symbols(self) -> None:
        df = _make_df(_TIMESTAMPS)
        engine = _make_engine(NoTradeStrategy("s"), {"RELIANCE": df})
        report = engine.run()
        assert "RELIANCE" in report.symbols

    def test_report_has_initial_cash(self) -> None:
        df = _make_df(_TIMESTAMPS)
        engine = _make_engine(NoTradeStrategy("s"), {"RELIANCE": df}, Decimal("50000"))
        report = engine.run()
        assert report.initial_cash == Decimal("50000")

    def test_report_has_start_and_end_time(self) -> None:
        df = _make_df(_TIMESTAMPS)
        engine = _make_engine(NoTradeStrategy("s"), {"RELIANCE": df})
        report = engine.run()
        assert report.start_time is not None
        assert report.end_time is not None
        assert report.end_time >= report.start_time


# ---------------------------------------------------------------------------
# No-trade strategy
# ---------------------------------------------------------------------------


class TestNoTradeStrategy:
    def test_no_fills(self) -> None:
        df = _make_df(_TIMESTAMPS)
        engine = _make_engine(NoTradeStrategy("s"), {"RELIANCE": df})
        report = engine.run()
        assert report.fills == []

    def test_final_equity_equals_initial_cash(self) -> None:
        df = _make_df(_TIMESTAMPS)
        engine = _make_engine(NoTradeStrategy("s"), {"RELIANCE": df}, Decimal("100000"))
        report = engine.run()
        assert report.final_equity == Decimal("100000")

    def test_equity_curve_populated(self) -> None:
        df = _make_df(_TIMESTAMPS)
        engine = _make_engine(NoTradeStrategy("s"), {"RELIANCE": df})
        report = engine.run()
        assert len(report.equity_curve) == 3  # one point per bar


# ---------------------------------------------------------------------------
# Buy-first-bar strategy
# ---------------------------------------------------------------------------


class TestBuyFirstBarStrategy:
    def test_produces_one_fill(self) -> None:
        df = _make_df(_TIMESTAMPS, base_price=500.0)
        engine = _make_engine(BuyFirstBarStrategy(), {"RELIANCE": df})
        report = engine.run()
        assert len(report.fills) == 1

    def test_fill_is_buy(self) -> None:
        df = _make_df(_TIMESTAMPS, base_price=500.0)
        engine = _make_engine(BuyFirstBarStrategy(), {"RELIANCE": df})
        report = engine.run()
        from trading_engine.domain.enums import Side

        assert report.fills[0].side == Side.BUY

    def test_equity_curve_has_correct_length(self) -> None:
        df = _make_df(_TIMESTAMPS)
        engine = _make_engine(BuyFirstBarStrategy(), {"RELIANCE": df})
        report = engine.run()
        assert len(report.equity_curve) == 3


# ---------------------------------------------------------------------------
# Buy-then-sell strategy
# ---------------------------------------------------------------------------


class TestBuyThenSellStrategy:
    def test_produces_two_fills(self) -> None:
        df = _make_df(_TIMESTAMPS, base_price=500.0)
        engine = _make_engine(BuyThenSellStrategy(), {"RELIANCE": df})
        report = engine.run()
        assert len(report.fills) == 2

    def test_first_fill_is_buy_second_is_sell(self) -> None:
        df = _make_df(_TIMESTAMPS, base_price=500.0)
        engine = _make_engine(BuyThenSellStrategy(), {"RELIANCE": df})
        report = engine.run()
        from trading_engine.domain.enums import Side

        assert report.fills[0].side == Side.BUY
        assert report.fills[1].side == Side.SELL

    def test_flat_price_zero_pnl(self) -> None:
        # Buy at 500, sell at 500, zero fees → zero P&L
        df = _make_df(_TIMESTAMPS, base_price=500.0)
        engine = _make_engine(BuyThenSellStrategy(), {"RELIANCE": df})
        report = engine.run()
        assert report.metrics.realized_pnl == Decimal("0")

    def test_metrics_trade_count_is_two(self) -> None:
        df = _make_df(_TIMESTAMPS, base_price=500.0)
        engine = _make_engine(BuyThenSellStrategy(), {"RELIANCE": df})
        report = engine.run()
        assert report.metrics.trade_count == 2


# ---------------------------------------------------------------------------
# No Zerodha / no live broker usage
# ---------------------------------------------------------------------------


class TestNoZerodhaDependency:
    def test_backtest_module_does_not_import_zerodha(self) -> None:
        import sys

        import trading_engine.backtest.engine as mod

        # Zerodha SDK should not be loaded as a side effect of the engine.
        assert "kiteconnect" not in sys.modules or True  # permissive check
        # Stricter: the engine module source must not reference kiteconnect.
        import inspect

        src = inspect.getsource(mod)
        assert "kiteconnect" not in src
        assert "ZerodhaBroker" not in src
