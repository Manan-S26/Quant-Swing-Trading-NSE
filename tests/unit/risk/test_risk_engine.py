"""Tests for RiskEngine."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trading_engine.domain.enums import Exchange, OrderType, ProductType, RiskReasonCode
from trading_engine.domain.models import PortfolioSnapshot, Position
from trading_engine.risk.engine import RiskEngine
from trading_engine.risk.kill_switch import KillSwitch
from trading_engine.risk.limits import RiskLimits
from trading_engine.strategy.signals import OrderIntent

_TS = datetime(2024, 1, 15, 10, 0, 0)


def _make_intent(
    *,
    symbol: str = "RELIANCE",
    side: str = "BUY",
    quantity: int = 1,
    order_type: str = "MARKET",
    product: str = "MIS",
    price: Decimal | None = Decimal("100"),
    trigger_price: Decimal | None = None,
) -> OrderIntent:
    return OrderIntent(
        strategy_id="test",
        symbol=symbol,
        exchange="NSE",
        side=side,
        quantity=quantity,
        order_type=order_type,
        product=product,
        price=price,
        trigger_price=trigger_price,
    )


def _make_snapshot(
    *,
    realized_pnl: Decimal = Decimal("0"),
    unrealized_pnl: Decimal = Decimal("0"),
    positions: list[Position] | None = None,
    cash: Decimal = Decimal("100000"),
) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        timestamp=_TS,
        cash=cash,
        positions=positions or [],
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        gross_exposure=Decimal("0"),
        net_exposure=Decimal("0"),
    )


def _make_position(
    symbol: str = "RELIANCE", quantity: int = 10, price: Decimal = Decimal("100")
) -> Position:
    return Position(
        symbol=symbol,
        exchange=Exchange.NSE,
        product=ProductType.MIS,
        quantity=quantity,
        average_price=price,
        last_price=price,
        updated_at=_TS,
    )


def _default_engine(**kwargs) -> RiskEngine:
    return RiskEngine(limits=RiskLimits(**kwargs))


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


class TestKillSwitch:
    def test_active_kill_switch_rejects(self):
        ks = KillSwitch()
        ks.activate("emergency stop")
        engine = RiskEngine(limits=RiskLimits(), kill_switch=ks)
        decision = engine.check_order_intent(_make_intent(), _make_snapshot(), _TS)
        assert not decision.approved
        assert decision.reason_code == RiskReasonCode.KILL_SWITCH_ACTIVE

    def test_inactive_kill_switch_passes(self):
        ks = KillSwitch()
        engine = RiskEngine(limits=RiskLimits(), kill_switch=ks)
        decision = engine.check_order_intent(_make_intent(), _make_snapshot(), _TS)
        assert decision.approved

    def test_engine_exposes_kill_switch(self):
        ks = KillSwitch()
        engine = RiskEngine(limits=RiskLimits(), kill_switch=ks)
        assert engine.kill_switch is ks


# ---------------------------------------------------------------------------
# Symbol allowlist
# ---------------------------------------------------------------------------


class TestSymbolCheck:
    def test_symbol_not_in_allowlist_rejects(self):
        engine = _default_engine(allowed_symbols={"TCS", "INFY"})
        decision = engine.check_order_intent(_make_intent(symbol="RELIANCE"), _make_snapshot(), _TS)
        assert not decision.approved
        assert decision.reason_code == RiskReasonCode.SYMBOL_NOT_ALLOWED

    def test_symbol_in_allowlist_passes(self):
        engine = _default_engine(allowed_symbols={"RELIANCE"})
        decision = engine.check_order_intent(_make_intent(symbol="RELIANCE"), _make_snapshot(), _TS)
        assert decision.approved

    def test_no_allowlist_allows_any_symbol(self):
        engine = _default_engine()
        decision = engine.check_order_intent(_make_intent(symbol="XYZABC"), _make_snapshot(), _TS)
        assert decision.approved


# ---------------------------------------------------------------------------
# Product type
# ---------------------------------------------------------------------------


class TestProductCheck:
    def test_disallowed_product_rejects(self):
        engine = _default_engine(allowed_product_types={ProductType.MIS})
        decision = engine.check_order_intent(_make_intent(product="CNC"), _make_snapshot(), _TS)
        assert not decision.approved
        assert decision.reason_code == RiskReasonCode.PRODUCT_NOT_ALLOWED

    def test_allowed_product_passes(self):
        engine = _default_engine(allowed_product_types={ProductType.MIS})
        decision = engine.check_order_intent(_make_intent(product="MIS"), _make_snapshot(), _TS)
        assert decision.approved


# ---------------------------------------------------------------------------
# Order type
# ---------------------------------------------------------------------------


class TestOrderTypeCheck:
    def test_disallowed_order_type_rejects(self):
        engine = _default_engine(allowed_order_types={OrderType.MARKET})
        decision = engine.check_order_intent(
            _make_intent(order_type="LIMIT", price=Decimal("100")), _make_snapshot(), _TS
        )
        assert not decision.approved
        assert decision.reason_code == RiskReasonCode.ORDER_TYPE_NOT_ALLOWED

    def test_allowed_order_type_passes(self):
        engine = _default_engine(allowed_order_types={OrderType.MARKET})
        decision = engine.check_order_intent(
            _make_intent(order_type="MARKET"), _make_snapshot(), _TS
        )
        assert decision.approved


# ---------------------------------------------------------------------------
# Order value
# ---------------------------------------------------------------------------


class TestOrderValueCheck:
    def test_order_exceeding_limit_rejects(self):
        engine = _default_engine(max_order_value=Decimal("999"))
        # price=100, qty=10 → value=1000 > 999
        decision = engine.check_order_intent(
            _make_intent(quantity=10, price=Decimal("100")),
            _make_snapshot(),
            _TS,
        )
        assert not decision.approved
        assert decision.reason_code == RiskReasonCode.ORDER_VALUE_LIMIT_BREACHED

    def test_order_at_limit_passes(self):
        engine = _default_engine(max_order_value=Decimal("1000"))
        decision = engine.check_order_intent(
            _make_intent(quantity=10, price=Decimal("100")),
            _make_snapshot(),
            _TS,
        )
        assert decision.approved

    def test_no_price_available_rejects(self):
        engine = _default_engine()
        intent = _make_intent(price=None, trigger_price=None)
        decision = engine.check_order_intent(intent, _make_snapshot(), _TS)
        assert not decision.approved
        assert decision.reason_code == RiskReasonCode.INVALID_ORDER

    def test_fallback_to_snapshot_last_price(self):
        engine = _default_engine(max_order_value=Decimal("50000"))
        pos = _make_position("RELIANCE", quantity=5, price=Decimal("100"))
        snapshot = _make_snapshot(positions=[pos])
        intent = _make_intent(price=None, trigger_price=None, quantity=1)
        decision = engine.check_order_intent(intent, snapshot, _TS)
        assert decision.approved


# ---------------------------------------------------------------------------
# Position count
# ---------------------------------------------------------------------------


class TestPositionCountCheck:
    def test_new_position_at_limit_rejects(self):
        engine = _default_engine(max_open_positions=1)
        pos = _make_position("TCS", quantity=10)
        snapshot = _make_snapshot(positions=[pos])
        # Buying a different symbol when already at limit
        decision = engine.check_order_intent(_make_intent(symbol="RELIANCE"), snapshot, _TS)
        assert not decision.approved
        assert decision.reason_code == RiskReasonCode.POSITION_LIMIT_BREACHED

    def test_adding_to_existing_position_passes(self):
        engine = _default_engine(max_open_positions=1)
        pos = _make_position("RELIANCE", quantity=5)
        snapshot = _make_snapshot(positions=[pos])
        # Adding to existing RELIANCE position — allowed even at limit
        decision = engine.check_order_intent(_make_intent(symbol="RELIANCE"), snapshot, _TS)
        assert decision.approved

    def test_sell_skips_position_count_check(self):
        engine = _default_engine(max_open_positions=1)
        pos = _make_position("TCS", quantity=10)
        snapshot = _make_snapshot(positions=[pos])
        decision = engine.check_order_intent(
            _make_intent(symbol="RELIANCE", side="SELL"), snapshot, _TS
        )
        # SELL skips position count — should not be rejected for this reason
        assert decision.reason_code != RiskReasonCode.POSITION_LIMIT_BREACHED


# ---------------------------------------------------------------------------
# Daily loss
# ---------------------------------------------------------------------------


class TestDailyLossCheck:
    def test_daily_loss_exceeds_limit_rejects(self):
        engine = _default_engine(max_daily_loss=Decimal("1000"))
        snapshot = _make_snapshot(realized_pnl=Decimal("-600"), unrealized_pnl=Decimal("-500"))
        decision = engine.check_order_intent(_make_intent(), snapshot, _TS)
        assert not decision.approved
        assert decision.reason_code == RiskReasonCode.DAILY_LOSS_LIMIT_BREACHED

    def test_daily_loss_at_limit_rejects(self):
        engine = _default_engine(max_daily_loss=Decimal("1000"))
        snapshot = _make_snapshot(realized_pnl=Decimal("-1001"), unrealized_pnl=Decimal("0"))
        decision = engine.check_order_intent(_make_intent(), snapshot, _TS)
        assert not decision.approved

    def test_profit_does_not_trigger_loss_check(self):
        engine = _default_engine(max_daily_loss=Decimal("1000"))
        snapshot = _make_snapshot(realized_pnl=Decimal("500"), unrealized_pnl=Decimal("200"))
        decision = engine.check_order_intent(_make_intent(), snapshot, _TS)
        assert decision.approved

    def test_small_loss_below_limit_passes(self):
        engine = _default_engine(max_daily_loss=Decimal("1000"))
        snapshot = _make_snapshot(realized_pnl=Decimal("-400"), unrealized_pnl=Decimal("-200"))
        decision = engine.check_order_intent(_make_intent(), snapshot, _TS)
        assert decision.approved


# ---------------------------------------------------------------------------
# Trades per day
# ---------------------------------------------------------------------------


class TestTradesPerDayCheck:
    def test_at_limit_rejects(self):
        engine = _default_engine(max_trades_per_day=2)
        snapshot = _make_snapshot()
        # Approve 2 orders to hit the limit
        engine.check_order_intent(_make_intent(), snapshot, _TS)
        engine.check_order_intent(_make_intent(), snapshot, _TS)
        # Third should be rejected
        decision = engine.check_order_intent(_make_intent(), snapshot, _TS)
        assert not decision.approved
        assert decision.reason_code == RiskReasonCode.RATE_LIMIT_BREACHED

    def test_reset_daily_state_resets_count(self):
        engine = _default_engine(max_trades_per_day=1)
        snapshot = _make_snapshot()
        engine.check_order_intent(_make_intent(), snapshot, _TS)
        engine.reset_daily_state()
        decision = engine.check_order_intent(_make_intent(), snapshot, _TS)
        assert decision.approved


# ---------------------------------------------------------------------------
# Orders per second
# ---------------------------------------------------------------------------


class TestOrdersPerSecondCheck:
    def test_at_rate_limit_rejects(self):
        engine = _default_engine(max_orders_per_second=2)
        snapshot = _make_snapshot()
        ts = datetime(2024, 1, 15, 10, 0, 0)
        engine.check_order_intent(_make_intent(), snapshot, ts)
        engine.check_order_intent(_make_intent(), snapshot, ts)
        decision = engine.check_order_intent(_make_intent(), snapshot, ts)
        assert not decision.approved
        assert decision.reason_code == RiskReasonCode.RATE_LIMIT_BREACHED

    def test_new_second_resets_rate_window(self):
        from datetime import timedelta

        engine = _default_engine(max_orders_per_second=1)
        snapshot = _make_snapshot()
        ts0 = datetime(2024, 1, 15, 10, 0, 0)
        ts1 = ts0 + timedelta(seconds=1)
        engine.check_order_intent(_make_intent(), snapshot, ts0)
        # 1 second later, window should have cleared
        decision = engine.check_order_intent(_make_intent(), snapshot, ts1)
        assert decision.approved


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------


class TestApproval:
    def test_all_checks_pass_returns_approved(self):
        engine = _default_engine()
        decision = engine.check_order_intent(_make_intent(), _make_snapshot(), _TS)
        assert decision.approved
        assert decision.reason_code == RiskReasonCode.APPROVED

    def test_approved_decision_has_id(self):
        engine = _default_engine()
        decision = engine.check_order_intent(_make_intent(), _make_snapshot(), _TS)
        assert decision.risk_decision_id.startswith("risk_")

    def test_rejected_decision_has_id(self):
        ks = KillSwitch()
        ks.activate("test")
        engine = RiskEngine(limits=RiskLimits(), kill_switch=ks)
        decision = engine.check_order_intent(_make_intent(), _make_snapshot(), _TS)
        assert not decision.approved
        assert decision.risk_decision_id.startswith("risk_")

    def test_default_timestamp_used_when_none_given(self):
        engine = _default_engine()
        # Should not raise — uses utcnow() internally
        decision = engine.check_order_intent(_make_intent(), _make_snapshot())
        assert decision.approved
