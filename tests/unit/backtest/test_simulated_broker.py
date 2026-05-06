"""Tests for SimulatedBroker."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from trading_engine.backtest.cost_model import CostModel
from trading_engine.backtest.portfolio import BacktestPortfolio
from trading_engine.backtest.simulated_broker import SimulatedBroker, UnsupportedOrderTypeError
from trading_engine.backtest.slippage_model import SlippageModel
from trading_engine.domain.models import TradeFill
from trading_engine.strategy.signals import Bar, OrderIntent


def _make_bar(
    symbol: str = "RELIANCE",
    open_: float = 490.0,
    high: float = 510.0,
    low: float = 485.0,
    close: float = 500.0,
    ts: str = "2024-01-15 09:15:00",
) -> Bar:
    return Bar(
        symbol=symbol,
        exchange="NSE",
        timestamp=datetime.fromisoformat(ts),
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=10000,
        interval="minute",
    )


def _make_intent(
    side: str = "BUY",
    order_type: str = "MARKET",
    quantity: int = 10,
    price: Decimal | None = None,
    trigger_price: Decimal | None = None,
) -> OrderIntent:
    return OrderIntent(
        strategy_id="test_strategy",
        symbol="RELIANCE",
        exchange="NSE",
        side=side,
        quantity=quantity,
        order_type=order_type,
        product="MIS",
        price=price,
        trigger_price=trigger_price,
    )


def _broker(cash: Decimal = Decimal("100000")) -> tuple[SimulatedBroker, BacktestPortfolio]:
    portfolio = BacktestPortfolio(initial_cash=cash)
    cost = CostModel(
        brokerage_per_order=Decimal("20"),
        brokerage_cap=Decimal("20"),
        stt_rate=Decimal("0"),
        exchange_txn_rate=Decimal("0"),
        sebi_rate=Decimal("0"),
        stamp_duty_rate=Decimal("0"),
        gst_rate=Decimal("0"),
    )
    slippage = SlippageModel(bps=Decimal("0"))
    broker = SimulatedBroker(portfolio, cost, slippage)
    return broker, portfolio


class TestMarketOrders:
    def test_market_buy_returns_fill(self) -> None:
        broker, _ = _broker()
        fill = broker.execute_order_intent(_make_intent("BUY", "MARKET"), _make_bar())
        assert isinstance(fill, TradeFill)

    def test_market_buy_fill_price_is_close(self) -> None:
        # Zero slippage → fill at close.
        broker, _ = _broker()
        bar = _make_bar(close=500.0)
        fill = broker.execute_order_intent(_make_intent("BUY", "MARKET"), bar)
        assert fill.price == Decimal("500.00")

    def test_market_buy_updates_portfolio(self) -> None:
        broker, portfolio = _broker(Decimal("100000"))
        broker.execute_order_intent(
            _make_intent("BUY", "MARKET", quantity=10), _make_bar(close=500.0)
        )
        pos = portfolio.get_position("RELIANCE")
        assert pos is not None
        assert pos.quantity == 10

    def test_market_sell_returns_fill(self) -> None:
        broker, portfolio = _broker()
        # Buy first.
        broker.execute_order_intent(_make_intent("BUY", "MARKET", quantity=10), _make_bar())
        fill = broker.execute_order_intent(_make_intent("SELL", "MARKET", quantity=10), _make_bar())
        assert isinstance(fill, TradeFill)

    def test_market_sell_reduces_position(self) -> None:
        broker, portfolio = _broker()
        broker.execute_order_intent(_make_intent("BUY", "MARKET", quantity=10), _make_bar())
        broker.execute_order_intent(_make_intent("SELL", "MARKET", quantity=5), _make_bar())
        pos = portfolio.get_position("RELIANCE")
        assert pos.quantity == 5


class TestLimitOrders:
    def test_limit_buy_fills_when_bar_low_touches(self) -> None:
        # bar low=485, limit=490 → 485 <= 490 → fills
        broker, _ = _broker()
        intent = _make_intent("BUY", "LIMIT", price=Decimal("490"))
        fill = broker.execute_order_intent(intent, _make_bar(low=485.0))
        assert fill is not None

    def test_limit_buy_does_not_fill_when_bar_low_above_limit(self) -> None:
        # bar low=495, limit=490 → 495 > 490 → no fill
        broker, _ = _broker()
        intent = _make_intent("BUY", "LIMIT", price=Decimal("490"))
        fill = broker.execute_order_intent(intent, _make_bar(low=495.0))
        assert fill is None

    def test_limit_buy_fill_price_is_limit(self) -> None:
        # Zero slippage → fill at limit price.
        broker, _ = _broker()
        intent = _make_intent("BUY", "LIMIT", price=Decimal("490"))
        fill = broker.execute_order_intent(intent, _make_bar(low=485.0))
        assert fill.price == Decimal("490.00")

    def test_limit_sell_fills_when_bar_high_touches(self) -> None:
        # bar high=510, limit=505 → 510 >= 505 → fills
        broker, portfolio = _broker()
        broker.execute_order_intent(_make_intent("BUY", "MARKET", quantity=10), _make_bar())
        intent = _make_intent("SELL", "LIMIT", quantity=10, price=Decimal("505"))
        fill = broker.execute_order_intent(intent, _make_bar(high=510.0))
        assert fill is not None

    def test_limit_sell_does_not_fill_when_bar_high_below_limit(self) -> None:
        # bar high=500, limit=510 → 500 < 510 → no fill
        broker, portfolio = _broker()
        broker.execute_order_intent(_make_intent("BUY", "MARKET", quantity=10), _make_bar())
        intent = _make_intent("SELL", "LIMIT", quantity=10, price=Decimal("510"))
        fill = broker.execute_order_intent(intent, _make_bar(high=500.0))
        assert fill is None


class TestUnsupportedOrders:
    def test_sl_order_raises(self) -> None:
        broker, _ = _broker()
        intent = _make_intent("BUY", "SL", trigger_price=Decimal("490"))
        with pytest.raises(UnsupportedOrderTypeError):
            broker.execute_order_intent(intent, _make_bar())

    def test_sl_m_order_raises(self) -> None:
        broker, _ = _broker()
        intent = _make_intent("BUY", "SL-M", trigger_price=Decimal("490"))
        with pytest.raises(UnsupportedOrderTypeError):
            broker.execute_order_intent(intent, _make_bar())


class TestFillContents:
    def test_fill_has_correct_symbol(self) -> None:
        broker, _ = _broker()
        fill = broker.execute_order_intent(_make_intent("BUY", "MARKET"), _make_bar())
        assert fill.symbol == "RELIANCE"

    def test_fill_has_correct_quantity(self) -> None:
        broker, _ = _broker()
        fill = broker.execute_order_intent(_make_intent("BUY", "MARKET", quantity=7), _make_bar())
        assert fill.quantity == 7

    def test_fill_has_positive_fees(self) -> None:
        # Use default cost model (flat Rs.20).
        portfolio = BacktestPortfolio(initial_cash=Decimal("100000"))
        broker = SimulatedBroker(portfolio, CostModel(), SlippageModel(bps=Decimal("0")))
        fill = broker.execute_order_intent(_make_intent("BUY", "MARKET"), _make_bar())
        assert fill.fees > 0
