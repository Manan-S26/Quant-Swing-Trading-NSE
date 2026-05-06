"""Tests for domain Pydantic models."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_engine.domain.enums import (
    Exchange,
    OrderStatus,
    OrderType,
    ProductType,
    RiskReasonCode,
    Side,
    TimeInForce,
)
from trading_engine.domain.models import (
    Instrument,
    InternalOrder,
    Money,
    PortfolioSnapshot,
    Position,
    RiskDecision,
    TradeFill,
)

NOW = datetime(2024, 1, 15, 9, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_internal_order(**overrides: object) -> InternalOrder:
    defaults: dict = dict(
        internal_order_id="ord_abc123",
        strategy_id="orb_v1",
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        side=Side.BUY,
        quantity=10,
        order_type=OrderType.MARKET,
        product=ProductType.MIS,
        created_at=NOW,
        updated_at=NOW,
    )
    defaults.update(overrides)
    return InternalOrder(**defaults)


def make_risk_decision(**overrides: object) -> RiskDecision:
    defaults: dict = dict(
        risk_decision_id="risk_abc123",
        approved=True,
        reason_code=RiskReasonCode.APPROVED,
        reason_message="All checks passed",
        timestamp=NOW,
    )
    defaults.update(overrides)
    return RiskDecision(**defaults)


def make_position(**overrides: object) -> Position:
    defaults: dict = dict(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        product=ProductType.MIS,
        quantity=10,
        average_price=Decimal("2800.00"),
        updated_at=NOW,
    )
    defaults.update(overrides)
    return Position(**defaults)


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------


class TestMoney:
    def test_valid_positive_amount(self) -> None:
        m = Money(amount=Decimal("1000.50"))
        assert m.amount == Decimal("1000.50")
        assert m.currency == "INR"

    def test_zero_amount_allowed(self) -> None:
        m = Money(amount=Decimal("0"))
        assert m.amount == Decimal("0")

    def test_negative_amount_allowed(self) -> None:
        # Negative money represents a loss or debit
        m = Money(amount=Decimal("-500"))
        assert m.amount == Decimal("-500")

    def test_custom_currency(self) -> None:
        m = Money(amount=Decimal("100"), currency="USD")
        assert m.currency == "USD"

    def test_empty_currency_raises(self) -> None:
        with pytest.raises(ValidationError, match="currency"):
            Money(amount=Decimal("100"), currency="")

    def test_whitespace_currency_raises(self) -> None:
        with pytest.raises(ValidationError, match="currency"):
            Money(amount=Decimal("100"), currency="   ")


# ---------------------------------------------------------------------------
# Instrument
# ---------------------------------------------------------------------------


class TestInstrument:
    def test_valid_instrument(self) -> None:
        inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE)
        assert inst.symbol == "RELIANCE"
        assert inst.lot_size == 1
        assert inst.is_active is True

    def test_empty_symbol_raises(self) -> None:
        with pytest.raises(ValidationError, match="symbol"):
            Instrument(symbol="", exchange=Exchange.NSE)

    def test_whitespace_symbol_raises(self) -> None:
        with pytest.raises(ValidationError, match="symbol"):
            Instrument(symbol="   ", exchange=Exchange.NSE)

    def test_zero_lot_size_raises(self) -> None:
        with pytest.raises(ValidationError, match="lot_size"):
            Instrument(symbol="RELIANCE", exchange=Exchange.NSE, lot_size=0)

    def test_negative_lot_size_raises(self) -> None:
        with pytest.raises(ValidationError, match="lot_size"):
            Instrument(symbol="RELIANCE", exchange=Exchange.NSE, lot_size=-1)

    def test_valid_tick_size(self) -> None:
        inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE, tick_size=Decimal("0.05"))
        assert inst.tick_size == Decimal("0.05")

    def test_zero_tick_size_raises(self) -> None:
        with pytest.raises(ValidationError, match="tick_size"):
            Instrument(symbol="RELIANCE", exchange=Exchange.NSE, tick_size=Decimal("0"))

    def test_negative_tick_size_raises(self) -> None:
        with pytest.raises(ValidationError, match="tick_size"):
            Instrument(symbol="RELIANCE", exchange=Exchange.NSE, tick_size=Decimal("-0.05"))

    def test_none_tick_size_allowed(self) -> None:
        inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE, tick_size=None)
        assert inst.tick_size is None


# ---------------------------------------------------------------------------
# RiskDecision
# ---------------------------------------------------------------------------


class TestRiskDecision:
    def test_approved_decision(self) -> None:
        rd = make_risk_decision()
        assert rd.approved is True
        assert rd.reason_code == RiskReasonCode.APPROVED

    def test_rejected_decision(self) -> None:
        rd = make_risk_decision(
            approved=False,
            reason_code=RiskReasonCode.LIVE_TRADING_DISABLED,
            reason_message="Live trading is disabled.",
        )
        assert rd.approved is False
        assert rd.reason_code == RiskReasonCode.LIVE_TRADING_DISABLED

    def test_empty_reason_message_raises(self) -> None:
        with pytest.raises(ValidationError, match="reason_message"):
            make_risk_decision(reason_message="")

    def test_whitespace_reason_message_raises(self) -> None:
        with pytest.raises(ValidationError, match="reason_message"):
            make_risk_decision(reason_message="   ")

    def test_rejected_with_approved_code_raises(self) -> None:
        with pytest.raises(ValidationError, match="reason_code"):
            make_risk_decision(
                approved=False,
                reason_code=RiskReasonCode.APPROVED,
                reason_message="This is inconsistent.",
            )

    def test_all_rejection_codes_work(self) -> None:
        rejection_codes = [
            RiskReasonCode.LIVE_TRADING_DISABLED,
            RiskReasonCode.DAILY_LOSS_LIMIT_BREACHED,
            RiskReasonCode.ORDER_VALUE_LIMIT_BREACHED,
            RiskReasonCode.KILL_SWITCH_ACTIVE,
            RiskReasonCode.MARKET_DATA_STALE,
        ]
        for code in rejection_codes:
            rd = make_risk_decision(
                approved=False,
                reason_code=code,
                reason_message=f"Rejected: {code}",
            )
            assert rd.approved is False
            assert rd.reason_code == code

    def test_checked_limits_defaults_to_empty_dict(self) -> None:
        rd = make_risk_decision()
        assert rd.checked_limits == {}

    def test_checked_limits_accepts_arbitrary_data(self) -> None:
        rd = make_risk_decision(checked_limits={"max_daily_loss": 1000, "used": 250.5})
        assert rd.checked_limits["max_daily_loss"] == 1000


# ---------------------------------------------------------------------------
# InternalOrder
# ---------------------------------------------------------------------------


class TestInternalOrderValid:
    def test_market_buy(self) -> None:
        order = make_internal_order()
        assert order.order_type == OrderType.MARKET
        assert order.side == Side.BUY
        assert order.status == OrderStatus.CREATED

    def test_limit_buy_with_price(self) -> None:
        order = make_internal_order(order_type=OrderType.LIMIT, price=Decimal("2800.00"))
        assert order.price == Decimal("2800.00")

    def test_sl_with_price_and_trigger(self) -> None:
        order = make_internal_order(
            order_type=OrderType.SL,
            price=Decimal("2790.00"),
            trigger_price=Decimal("2795.00"),
        )
        assert order.trigger_price == Decimal("2795.00")

    def test_sl_m_with_trigger(self) -> None:
        order = make_internal_order(
            order_type=OrderType.SL_M,
            trigger_price=Decimal("2790.00"),
        )
        assert order.order_type == OrderType.SL_M

    def test_default_time_in_force_is_day(self) -> None:
        order = make_internal_order()
        assert order.time_in_force == TimeInForce.DAY

    def test_updated_at_same_as_created_at(self) -> None:
        order = make_internal_order(created_at=NOW, updated_at=NOW)
        assert order.updated_at == order.created_at

    def test_updated_at_after_created_at(self) -> None:
        from datetime import timedelta

        later = NOW + timedelta(minutes=5)
        order = make_internal_order(created_at=NOW, updated_at=later)
        assert order.updated_at > order.created_at


class TestInternalOrderInvalid:
    def test_empty_strategy_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            make_internal_order(strategy_id="")

    def test_empty_symbol_raises(self) -> None:
        with pytest.raises(ValidationError):
            make_internal_order(symbol="")

    def test_zero_quantity_raises(self) -> None:
        with pytest.raises(ValidationError, match="quantity"):
            make_internal_order(quantity=0)

    def test_negative_quantity_raises(self) -> None:
        with pytest.raises(ValidationError, match="quantity"):
            make_internal_order(quantity=-5)

    def test_negative_price_raises(self) -> None:
        with pytest.raises(ValidationError, match="price"):
            make_internal_order(
                order_type=OrderType.LIMIT,
                price=Decimal("-100"),
            )

    def test_limit_without_price_raises(self) -> None:
        with pytest.raises(ValidationError, match="price"):
            make_internal_order(order_type=OrderType.LIMIT, price=None)

    def test_sl_without_trigger_raises(self) -> None:
        with pytest.raises(ValidationError, match="trigger_price"):
            make_internal_order(
                order_type=OrderType.SL,
                price=Decimal("2790.00"),
                trigger_price=None,
            )

    def test_sl_m_without_trigger_raises(self) -> None:
        with pytest.raises(ValidationError, match="trigger_price"):
            make_internal_order(order_type=OrderType.SL_M, trigger_price=None)

    def test_updated_at_before_created_at_raises(self) -> None:
        from datetime import timedelta

        earlier = NOW - timedelta(minutes=5)
        with pytest.raises(ValidationError, match="updated_at"):
            make_internal_order(created_at=NOW, updated_at=earlier)


# ---------------------------------------------------------------------------
# TradeFill
# ---------------------------------------------------------------------------


class TestTradeFill:
    def _make(self, **overrides: object) -> TradeFill:
        defaults: dict = dict(
            fill_id="fill_abc123",
            internal_order_id="ord_abc123",
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=Side.BUY,
            quantity=10,
            price=Decimal("2800.00"),
            timestamp=NOW,
        )
        defaults.update(overrides)
        return TradeFill(**defaults)

    def test_valid_fill(self) -> None:
        fill = self._make()
        assert fill.quantity == 10
        assert fill.fees == Decimal("0")

    def test_with_fees(self) -> None:
        fill = self._make(fees=Decimal("20.00"))
        assert fill.fees == Decimal("20.00")

    def test_empty_internal_order_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make(internal_order_id="")

    def test_empty_symbol_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make(symbol="")

    def test_zero_quantity_raises(self) -> None:
        with pytest.raises(ValidationError, match="quantity"):
            self._make(quantity=0)

    def test_zero_price_raises(self) -> None:
        with pytest.raises(ValidationError, match="price"):
            self._make(price=Decimal("0"))

    def test_negative_price_raises(self) -> None:
        with pytest.raises(ValidationError, match="price"):
            self._make(price=Decimal("-1"))

    def test_negative_fees_raises(self) -> None:
        with pytest.raises(ValidationError, match="fees"):
            self._make(fees=Decimal("-0.01"))


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------


class TestPosition:
    def test_valid_position(self) -> None:
        pos = make_position()
        assert pos.symbol == "RELIANCE"
        assert pos.realized_pnl == Decimal("0")

    def test_empty_symbol_raises(self) -> None:
        with pytest.raises(ValidationError, match="symbol"):
            make_position(symbol="")

    def test_negative_average_price_raises(self) -> None:
        with pytest.raises(ValidationError, match="average_price"):
            make_position(average_price=Decimal("-1"))

    def test_zero_average_price_allowed(self) -> None:
        # Zero average price is valid (e.g. for bonus shares or initialisation)
        pos = make_position(average_price=Decimal("0"))
        assert pos.average_price == Decimal("0")

    def test_last_price_none_allowed(self) -> None:
        pos = make_position(last_price=None)
        assert pos.last_price is None

    def test_negative_last_price_raises(self) -> None:
        with pytest.raises(ValidationError, match="last_price"):
            make_position(last_price=Decimal("-1"))

    def test_negative_pnl_allowed(self) -> None:
        pos = make_position(realized_pnl=Decimal("-500"), unrealized_pnl=Decimal("-200"))
        assert pos.realized_pnl == Decimal("-500")

    def test_quantity_can_be_negative_for_short(self) -> None:
        # Short positions have negative quantity
        pos = make_position(quantity=-5)
        assert pos.quantity == -5


# ---------------------------------------------------------------------------
# PortfolioSnapshot
# ---------------------------------------------------------------------------


class TestPortfolioSnapshot:
    def test_valid_snapshot(self) -> None:
        snap = PortfolioSnapshot(
            timestamp=NOW,
            cash=Decimal("50000"),
            positions=[make_position()],
            realized_pnl=Decimal("1000"),
            unrealized_pnl=Decimal("250"),
            gross_exposure=Decimal("28000"),
            net_exposure=Decimal("28000"),
        )
        assert len(snap.positions) == 1
        assert snap.cash == Decimal("50000")

    def test_negative_cash_allowed(self) -> None:
        snap = PortfolioSnapshot(
            timestamp=NOW,
            cash=Decimal("-1000"),
            positions=[],
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            gross_exposure=Decimal("0"),
            net_exposure=Decimal("0"),
        )
        assert snap.cash == Decimal("-1000")

    def test_zero_gross_exposure_allowed(self) -> None:
        snap = PortfolioSnapshot(
            timestamp=NOW,
            cash=Decimal("100000"),
            positions=[],
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            gross_exposure=Decimal("0"),
            net_exposure=Decimal("0"),
        )
        assert snap.gross_exposure == Decimal("0")

    def test_negative_gross_exposure_raises(self) -> None:
        with pytest.raises(ValidationError, match="gross_exposure"):
            PortfolioSnapshot(
                timestamp=NOW,
                cash=Decimal("100000"),
                positions=[],
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                gross_exposure=Decimal("-1"),
                net_exposure=Decimal("0"),
            )

    def test_empty_positions_list_valid(self) -> None:
        snap = PortfolioSnapshot(
            timestamp=NOW,
            cash=Decimal("100000"),
            positions=[],
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            gross_exposure=Decimal("0"),
            net_exposure=Decimal("0"),
        )
        assert snap.positions == []
