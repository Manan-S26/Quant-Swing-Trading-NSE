"""Tests for strategy base class, domain objects, and broker safety gate."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from trading_engine.broker.base import Broker
from trading_engine.common.exceptions import LiveTradingDisabledError, OrderValidationError
from trading_engine.strategy.base import Strategy, StrategyContext
from trading_engine.strategy.signals import Bar, OrderIntent, Signal, Tick


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def make_bar(
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
    close: str = "2800.00",
) -> Bar:
    return Bar(
        symbol=symbol,
        exchange=exchange,
        timestamp=datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc),
        open=Decimal("2790.00"),
        high=Decimal("2820.00"),
        low=Decimal("2785.00"),
        close=Decimal(close),
        volume=100_000,
    )


def make_context(mode: str = "backtest") -> StrategyContext:
    return StrategyContext(
        strategy_id="test_strategy_v1",
        mode=mode,
        config={"max_position": 10},
    )


class DoNothingStrategy(Strategy):
    """Minimal concrete strategy for testing the base class."""

    def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
        return []


class BuyOnEveryBarStrategy(Strategy):
    """Returns one BUY OrderIntent per bar."""

    def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
        return [
            OrderIntent(
                strategy_id=context.strategy_id,
                symbol=bar.symbol,
                exchange=bar.exchange,
                side="BUY",
                quantity=5,
                order_type="MARKET",
                product="MIS",
                reason="test_buy",
            )
        ]


# ---------------------------------------------------------------------------
# Strategy base class
# ---------------------------------------------------------------------------

class TestStrategyCanBeSubclassed:
    def test_do_nothing_strategy_instantiates(self) -> None:
        s = DoNothingStrategy("do_nothing_v1")
        assert s.strategy_id == "do_nothing_v1"

    def test_on_bar_returns_empty_list_for_do_nothing(self) -> None:
        s = DoNothingStrategy("do_nothing_v1")
        result = s.on_bar(make_bar(), make_context())
        assert result == []

    def test_on_tick_returns_empty_list_by_default(self) -> None:
        s = DoNothingStrategy("do_nothing_v1")
        tick = Tick(
            symbol="RELIANCE",
            exchange="NSE",
            timestamp=datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc),
            last_price=Decimal("2800.00"),
            volume=500,
        )
        result = s.on_tick(tick, make_context())
        assert result == []

    def test_abstract_strategy_cannot_be_instantiated(self) -> None:
        with pytest.raises(TypeError):
            Strategy("cant_instantiate")  # type: ignore[abstract]


class TestStrategyReturnsOrderIntents:
    def test_on_bar_returns_order_intents(self) -> None:
        s = BuyOnEveryBarStrategy("buy_strategy_v1")
        context = make_context()
        results = s.on_bar(make_bar(), context)
        assert len(results) == 1
        assert isinstance(results[0], OrderIntent)

    def test_order_intent_has_correct_side(self) -> None:
        s = BuyOnEveryBarStrategy("buy_strategy_v1")
        results = s.on_bar(make_bar(), make_context())
        assert results[0].side == "BUY"

    def test_order_intent_has_positive_quantity(self) -> None:
        s = BuyOnEveryBarStrategy("buy_strategy_v1")
        results = s.on_bar(make_bar(), make_context())
        assert results[0].quantity > 0

    def test_strategy_id_propagated_to_order_intent(self) -> None:
        s = BuyOnEveryBarStrategy("buy_strategy_v1")
        context = make_context()
        results = s.on_bar(make_bar(), context)
        assert results[0].strategy_id == "test_strategy_v1"


# ---------------------------------------------------------------------------
# StrategyContext
# ---------------------------------------------------------------------------

class TestStrategyContext:
    def test_backtest_mode_flag(self) -> None:
        ctx = make_context("backtest")
        assert ctx.is_backtest is True
        assert ctx.is_paper is False
        assert ctx.is_live is False

    def test_paper_mode_flag(self) -> None:
        ctx = make_context("paper")
        assert ctx.is_paper is True
        assert ctx.is_backtest is False
        assert ctx.is_live is False

    def test_live_mode_flag(self) -> None:
        ctx = make_context("live")
        assert ctx.is_live is True

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown mode"):
            StrategyContext("s", "invalid_mode", {})


# ---------------------------------------------------------------------------
# OrderIntent validation
# ---------------------------------------------------------------------------

class TestOrderIntentValidation:
    def test_valid_market_buy(self) -> None:
        intent = OrderIntent(
            strategy_id="s1",
            symbol="INFY",
            exchange="NSE",
            side="BUY",
            quantity=10,
            order_type="MARKET",
            product="MIS",
        )
        assert intent.quantity == 10

    def test_zero_quantity_raises(self) -> None:
        with pytest.raises(OrderValidationError, match="quantity"):
            OrderIntent(
                strategy_id="s1",
                symbol="INFY",
                exchange="NSE",
                side="BUY",
                quantity=0,
                order_type="MARKET",
                product="MIS",
            )

    def test_negative_quantity_raises(self) -> None:
        with pytest.raises(OrderValidationError, match="quantity"):
            OrderIntent(
                strategy_id="s1",
                symbol="INFY",
                exchange="NSE",
                side="BUY",
                quantity=-5,
                order_type="MARKET",
                product="MIS",
            )

    def test_invalid_side_raises(self) -> None:
        with pytest.raises(OrderValidationError, match="side"):
            OrderIntent(
                strategy_id="s1",
                symbol="INFY",
                exchange="NSE",
                side="LONG",  # invalid
                quantity=10,
                order_type="MARKET",
                product="MIS",
            )

    def test_invalid_order_type_raises(self) -> None:
        with pytest.raises(OrderValidationError, match="order_type"):
            OrderIntent(
                strategy_id="s1",
                symbol="INFY",
                exchange="NSE",
                side="BUY",
                quantity=10,
                order_type="FOK",  # invalid
                product="MIS",
            )

    def test_limit_order_without_price_raises(self) -> None:
        with pytest.raises(OrderValidationError, match="price"):
            OrderIntent(
                strategy_id="s1",
                symbol="INFY",
                exchange="NSE",
                side="BUY",
                quantity=10,
                order_type="LIMIT",
                product="MIS",
                # price intentionally omitted
            )

    def test_limit_order_with_price_valid(self) -> None:
        intent = OrderIntent(
            strategy_id="s1",
            symbol="INFY",
            exchange="NSE",
            side="BUY",
            quantity=10,
            order_type="LIMIT",
            product="MIS",
            price=Decimal("1800.00"),
        )
        assert intent.price == Decimal("1800.00")

    def test_sl_order_requires_trigger_price(self) -> None:
        with pytest.raises(OrderValidationError, match="trigger_price"):
            OrderIntent(
                strategy_id="s1",
                symbol="INFY",
                exchange="NSE",
                side="SELL",
                quantity=10,
                order_type="SL",
                product="MIS",
                price=Decimal("1790.00"),
                # trigger_price intentionally omitted
            )


# ---------------------------------------------------------------------------
# Broker safety gate — live order placement must be blocked
# ---------------------------------------------------------------------------

class StubBroker(Broker):
    """Minimal concrete broker for testing the abstract interface."""

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def get_positions(self) -> list[dict]:
        return []

    def get_orders(self) -> list[dict]:
        return []

    def get_trades(self) -> list[dict]:
        return []

    def get_margins(self) -> dict:
        return {}


class TestBrokerLiveOrderBlocked:
    def setup_method(self) -> None:
        self.broker = StubBroker()

    def test_place_order_raises_live_trading_disabled(self) -> None:
        with pytest.raises(LiveTradingDisabledError):
            self.broker.place_order(symbol="RELIANCE", quantity=10)

    def test_modify_order_raises_live_trading_disabled(self) -> None:
        with pytest.raises(LiveTradingDisabledError):
            self.broker.modify_order(order_id="abc123", price=2800)

    def test_cancel_order_raises_live_trading_disabled(self) -> None:
        with pytest.raises(LiveTradingDisabledError):
            self.broker.cancel_order(order_id="abc123")

    def test_read_only_methods_do_not_raise(self) -> None:
        # These should not raise — they are safe read operations.
        assert self.broker.get_positions() == []
        assert self.broker.get_orders() == []
        assert self.broker.get_trades() == []
        assert self.broker.get_margins() == {}
