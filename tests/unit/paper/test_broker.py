"""Tests for PaperExecutionBroker."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from trading_engine.backtest.cost_model import CostModel
from trading_engine.backtest.slippage_model import SlippageModel
from trading_engine.paper.broker import PaperExecutionBroker, UnsupportedOrderTypeError
from trading_engine.paper.portfolio import PaperPortfolio
from trading_engine.strategy.signals import Bar, OrderIntent

_TS = datetime(2024, 1, 15, 9, 30)


def _make_bar(
    symbol: str = "RELIANCE",
    price: float = 100.0,
    ts: datetime = _TS,
) -> Bar:
    return Bar(
        symbol=symbol,
        exchange="NSE",
        timestamp=ts,
        open=Decimal(str(price)),
        high=Decimal(str(price + 10)),
        low=Decimal(str(price - 10)),
        close=Decimal(str(price)),
        volume=1000,
        interval="minute",
    )


def _make_intent(
    *,
    symbol: str = "RELIANCE",
    side: str = "BUY",
    quantity: int = 10,
    order_type: str = "MARKET",
    price: Decimal | None = None,
) -> OrderIntent:
    return OrderIntent(
        strategy_id="test",
        symbol=symbol,
        exchange="NSE",
        side=side,
        quantity=quantity,
        order_type=order_type,
        product="MIS",
        price=price,
    )


def _make_broker(
    initial_cash: Decimal = Decimal("100000"),
    bps: Decimal = Decimal("0"),
) -> tuple[PaperExecutionBroker, PaperPortfolio]:
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
    slippage = SlippageModel(bps=bps)
    broker = PaperExecutionBroker(portfolio, cost, slippage)
    return broker, portfolio


class TestMarketOrders:
    def test_market_buy_fills(self):
        broker, portfolio = _make_broker()
        intent = _make_intent(side="BUY", quantity=10)
        fill = broker.execute_order_intent(intent, _make_bar(price=100.0))
        assert fill is not None
        assert fill.quantity == 10
        assert fill.price == Decimal("100")  # 0 slippage

    def test_market_sell_fills_when_position_exists(self):
        broker, portfolio = _make_broker()
        # First buy
        broker.execute_order_intent(_make_intent(side="BUY", quantity=10), _make_bar(price=100.0))
        # Then sell
        fill = broker.execute_order_intent(
            _make_intent(side="SELL", quantity=10), _make_bar(price=110.0)
        )
        assert fill is not None
        assert fill.quantity == 10
        assert fill.price == Decimal("110")

    def test_market_buy_updates_portfolio(self):
        broker, portfolio = _make_broker()
        broker.execute_order_intent(_make_intent(side="BUY", quantity=10), _make_bar(price=100.0))
        pos = portfolio.get_position("RELIANCE")
        assert pos is not None
        assert pos.quantity == 10


class TestLimitOrders:
    def test_limit_buy_fills_when_touched(self):
        # bar.low (90) <= limit (95): fills
        broker, _ = _make_broker()
        intent = _make_intent(side="BUY", order_type="LIMIT", price=Decimal("95"))
        bar = Bar(
            symbol="RELIANCE",
            exchange="NSE",
            timestamp=_TS,
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("90"),
            close=Decimal("100"),
            volume=1000,
        )
        fill = broker.execute_order_intent(intent, bar)
        assert fill is not None
        assert fill.price == Decimal("95")  # 0 slippage

    def test_limit_buy_does_not_fill_when_not_touched(self):
        # bar.low (98) > limit (95): no fill
        broker, _ = _make_broker()
        intent = _make_intent(side="BUY", order_type="LIMIT", price=Decimal("95"))
        bar = Bar(
            symbol="RELIANCE",
            exchange="NSE",
            timestamp=_TS,
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("98"),
            close=Decimal("100"),
            volume=1000,
        )
        fill = broker.execute_order_intent(intent, bar)
        assert fill is None

    def test_limit_sell_fills_when_touched(self):
        broker, portfolio = _make_broker()
        # Buy first
        broker.execute_order_intent(_make_intent(side="BUY", quantity=10), _make_bar(price=100.0))
        # Limit sell at 110, bar.high = 115
        intent = _make_intent(side="SELL", order_type="LIMIT", price=Decimal("110"), quantity=10)
        bar = Bar(
            symbol="RELIANCE",
            exchange="NSE",
            timestamp=_TS,
            open=Decimal("100"),
            high=Decimal("115"),
            low=Decimal("98"),
            close=Decimal("105"),
            volume=1000,
        )
        fill = broker.execute_order_intent(intent, bar)
        assert fill is not None
        assert fill.price == Decimal("110")

    def test_limit_sell_does_not_fill_when_not_touched(self):
        broker, portfolio = _make_broker()
        broker.execute_order_intent(_make_intent(side="BUY", quantity=10), _make_bar(price=100.0))
        # Limit sell at 120, bar.high = 115: no fill
        intent = _make_intent(side="SELL", order_type="LIMIT", price=Decimal("120"), quantity=10)
        bar = Bar(
            symbol="RELIANCE",
            exchange="NSE",
            timestamp=_TS,
            open=Decimal("100"),
            high=Decimal("115"),
            low=Decimal("98"),
            close=Decimal("105"),
            volume=1000,
        )
        fill = broker.execute_order_intent(intent, bar)
        assert fill is None


class TestUnsupportedOrderTypes:
    def test_sl_raises(self):
        broker, _ = _make_broker()
        intent = OrderIntent(
            strategy_id="test",
            symbol="RELIANCE",
            exchange="NSE",
            side="BUY",
            quantity=1,
            order_type="SL",
            product="MIS",
            trigger_price=Decimal("90"),
        )
        with pytest.raises(UnsupportedOrderTypeError):
            broker.execute_order_intent(intent, _make_bar())

    def test_slm_raises(self):
        broker, _ = _make_broker()
        intent = OrderIntent(
            strategy_id="test",
            symbol="RELIANCE",
            exchange="NSE",
            side="BUY",
            quantity=1,
            order_type="SL-M",
            product="MIS",
            trigger_price=Decimal("90"),
        )
        with pytest.raises(UnsupportedOrderTypeError):
            broker.execute_order_intent(intent, _make_bar())


class TestSlippage:
    def test_market_buy_applies_slippage_upward(self):
        broker, _ = _make_broker(bps=Decimal("100"))  # 1% slippage
        intent = _make_intent(side="BUY", quantity=1)
        fill = broker.execute_order_intent(intent, _make_bar(price=100.0))
        assert fill is not None
        assert fill.price > Decimal("100")

    def test_market_sell_applies_slippage_downward(self):
        broker, portfolio = _make_broker(bps=Decimal("100"))
        # Buy with 0-slippage broker first, then sell with slippage broker
        zero_broker, _ = _make_broker(bps=Decimal("0"))
        # Share the same portfolio
        portfolio2 = PaperPortfolio(initial_cash=Decimal("100000"))
        from trading_engine.backtest.cost_model import CostModel
        from trading_engine.backtest.slippage_model import SlippageModel

        cost = CostModel(
            brokerage_per_order=Decimal("0"),
            brokerage_cap=Decimal("0"),
            stt_rate=Decimal("0"),
            exchange_txn_rate=Decimal("0"),
            sebi_rate=Decimal("0"),
            stamp_duty_rate=Decimal("0"),
            gst_rate=Decimal("0"),
        )
        broker2 = PaperExecutionBroker(portfolio2, cost, SlippageModel(bps=Decimal("100")))
        broker2.execute_order_intent(_make_intent(side="BUY", quantity=1), _make_bar(price=100.0))
        fill = broker2.execute_order_intent(
            _make_intent(side="SELL", quantity=1), _make_bar(price=100.0)
        )
        assert fill is not None
        assert fill.price < Decimal("100")
