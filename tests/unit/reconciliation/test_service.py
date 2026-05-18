"""Tests for ReconciliationService.

All tests use fake brokers — no real Zerodha calls, no credentials.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from trading_engine.domain.enums import Exchange, OrderStatus, OrderType, ProductType, Side
from trading_engine.domain.identifiers import generate_internal_order_id
from trading_engine.domain.models import InternalOrder
from trading_engine.execution.ledger import OrderLedger
from trading_engine.reconciliation.models import (
    CODE_INVALID_TRANSITION,
    CODE_MAPPING_ERROR,
    CODE_MISSING_IN_BROKER,
    CODE_STATUS_MISMATCH_UPDATED,
    CODE_UNKNOWN_BROKER_ORDER,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
)
from trading_engine.reconciliation.service import ReconciliationService

_TS = datetime(2024, 1, 15, 9, 30, 0)

# ---------------------------------------------------------------------------
# Fake raw Zerodha order dicts
# ---------------------------------------------------------------------------

_RAW_OPEN = {
    "order_id": "ORD001",
    "exchange": "NSE",
    "tradingsymbol": "RELIANCE",
    "transaction_type": "BUY",
    "order_type": "LIMIT",
    "product": "MIS",
    "quantity": 10,
    "price": 2800.0,
    "trigger_price": 0.0,
    "validity": "DAY",
    "status": "OPEN",
    "order_timestamp": "2024-01-15 09:15:00",
    "exchange_update_timestamp": "2024-01-15 09:15:00",
}

_RAW_COMPLETE = {**_RAW_OPEN, "order_id": "ORD001", "status": "COMPLETE"}

_RAW_UNKNOWN_SYMBOL = {
    **_RAW_OPEN,
    "order_id": "ORD999",
    "tradingsymbol": "TCS",
}

_RAW_BAD = {
    "order_id": "ORD_BAD",
    # Missing tradingsymbol, exchange, etc. → BrokerMappingError
}

_FAKE_POSITION = {
    "tradingsymbol": "RELIANCE",
    "exchange": "NSE",
    "product": "MIS",
    "quantity": 10,
    "average_price": 2795.0,
    "last_price": 2800.0,
    "realised": 0.0,
    "unrealised": 50.0,
}


# ---------------------------------------------------------------------------
# Fake broker
# ---------------------------------------------------------------------------


class FakeBroker:
    """Minimal fake broker for reconciliation tests."""

    def __init__(
        self,
        orders: list[dict[str, Any]] | None = None,
        positions: list[dict[str, Any]] | None = None,
    ) -> None:
        self._orders = orders or []
        self._positions = positions or []

    def get_orders(self) -> list[dict[str, Any]]:
        return list(self._orders)

    def get_positions(self) -> list[dict[str, Any]]:
        # Return as a plain list (service handles both list and {"net": [...]} dict)
        return list(self._positions)

    # Verify these are NEVER called during reconciliation
    def place_order(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("place_order must not be called during reconciliation")

    def modify_order(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("modify_order must not be called during reconciliation")

    def cancel_order(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("cancel_order must not be called during reconciliation")


# ---------------------------------------------------------------------------
# Ledger helpers
# ---------------------------------------------------------------------------


def _make_submitted_order(
    broker_order_id: str,
    symbol: str = "RELIANCE",
    status: OrderStatus = OrderStatus.SUBMITTED,
) -> InternalOrder:
    """Create a ledger order that has already been submitted (has broker_order_id)."""
    return InternalOrder(
        internal_order_id=generate_internal_order_id(),
        broker_order_id=broker_order_id,
        strategy_id="test",
        symbol=symbol,
        exchange=Exchange.NSE,
        side=Side.BUY,
        quantity=10,
        order_type=OrderType.LIMIT,
        product=ProductType.MIS,
        price=Decimal("2800"),
        status=status,
        created_at=_TS,
        updated_at=_TS,
    )


def _make_open_order(broker_order_id: str, symbol: str = "RELIANCE") -> InternalOrder:
    return _make_submitted_order(broker_order_id, symbol, status=OrderStatus.OPEN)


def _make_ledger_with(*orders: InternalOrder) -> OrderLedger:
    ledger = OrderLedger()
    for o in orders:
        ledger.add_order(o)
    return ledger


# ---------------------------------------------------------------------------
# Tests: empty cases
# ---------------------------------------------------------------------------


class TestReconcileEmpty:
    def test_empty_broker_empty_ledger(self):
        service = ReconciliationService(FakeBroker(), OrderLedger())
        report = service.reconcile()
        assert report.broker_order_count == 0
        assert report.ledger_order_count == 0
        assert report.matched_orders == 0
        assert report.missing_in_broker == 0
        assert report.unknown_broker_orders == 0
        assert report.status_mismatches == 0
        assert report.success is True
        assert report.discrepancies == []

    def test_empty_broker_with_ledger_orders_no_broker_id(self):
        # Ledger orders without broker_order_id are skipped during reconciliation
        order = InternalOrder(
            internal_order_id=generate_internal_order_id(),
            strategy_id="test",
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=Side.BUY,
            quantity=5,
            order_type=OrderType.MARKET,
            product=ProductType.MIS,
            status=OrderStatus.CREATED,
            created_at=_TS,
            updated_at=_TS,
        )
        ledger = _make_ledger_with(order)
        service = ReconciliationService(FakeBroker(), ledger)
        report = service.reconcile()
        assert report.missing_in_broker == 0  # no broker_order_id → skipped
        assert report.success is True


# ---------------------------------------------------------------------------
# Tests: matching
# ---------------------------------------------------------------------------


class TestReconcileMatching:
    def test_matched_order_same_status_no_discrepancy(self):
        order = _make_open_order("ORD001")
        ledger = _make_ledger_with(order)
        broker = FakeBroker(orders=[_RAW_OPEN])
        service = ReconciliationService(broker, ledger)
        report = service.reconcile()
        assert report.matched_orders == 1
        assert report.missing_in_broker == 0
        assert report.unknown_broker_orders == 0
        assert report.status_mismatches == 0
        # LOW discrepancies only (status_mismatch_updated) — none here
        high = [d for d in report.discrepancies if d.severity == SEVERITY_HIGH]
        assert high == []

    def test_broker_order_count_correct(self):
        order = _make_open_order("ORD001")
        ledger = _make_ledger_with(order)
        broker = FakeBroker(orders=[_RAW_OPEN])
        report = ReconciliationService(broker, ledger).reconcile()
        assert report.broker_order_count == 1
        assert report.ledger_order_count == 1


# ---------------------------------------------------------------------------
# Tests: missing in broker
# ---------------------------------------------------------------------------


class TestMissingInBroker:
    def test_ledger_order_not_in_broker(self):
        order = _make_submitted_order("ORD_GONE")
        ledger = _make_ledger_with(order)
        broker = FakeBroker(orders=[])  # empty — broker knows nothing
        report = ReconciliationService(broker, ledger).reconcile()
        assert report.missing_in_broker == 1
        assert report.success is False
        codes = [d.code for d in report.discrepancies]
        assert CODE_MISSING_IN_BROKER in codes

    def test_missing_discrepancy_is_high_severity(self):
        order = _make_submitted_order("ORD_GONE")
        ledger = _make_ledger_with(order)
        report = ReconciliationService(FakeBroker(), ledger).reconcile()
        d = next(x for x in report.discrepancies if x.code == CODE_MISSING_IN_BROKER)
        assert d.severity == SEVERITY_HIGH
        assert d.broker_order_id == "ORD_GONE"

    def test_missing_discrepancy_has_symbol(self):
        order = _make_submitted_order("ORD_GONE", symbol="TCS")
        ledger = _make_ledger_with(order)
        report = ReconciliationService(FakeBroker(), ledger).reconcile()
        d = next(x for x in report.discrepancies if x.code == CODE_MISSING_IN_BROKER)
        assert d.symbol == "TCS"


# ---------------------------------------------------------------------------
# Tests: unknown broker order
# ---------------------------------------------------------------------------


class TestUnknownBrokerOrder:
    def test_broker_order_not_in_ledger(self):
        broker = FakeBroker(orders=[_RAW_UNKNOWN_SYMBOL])
        report = ReconciliationService(broker, OrderLedger()).reconcile()
        assert report.unknown_broker_orders == 1
        codes = [d.code for d in report.discrepancies]
        assert CODE_UNKNOWN_BROKER_ORDER in codes

    def test_unknown_broker_order_is_medium_severity(self):
        broker = FakeBroker(orders=[_RAW_UNKNOWN_SYMBOL])
        report = ReconciliationService(broker, OrderLedger()).reconcile()
        d = next(x for x in report.discrepancies if x.code == CODE_UNKNOWN_BROKER_ORDER)
        assert d.severity == SEVERITY_MEDIUM

    def test_unknown_broker_order_success_still_true(self):
        # UNKNOWN_BROKER_ORDER is MEDIUM — does not set success=False
        broker = FakeBroker(orders=[_RAW_UNKNOWN_SYMBOL])
        report = ReconciliationService(broker, OrderLedger()).reconcile()
        assert report.success is True


# ---------------------------------------------------------------------------
# Tests: status mismatch — valid transition
# ---------------------------------------------------------------------------


class TestStatusMismatchValidTransition:
    def test_status_updated_when_transition_valid(self):
        # Ledger: SUBMITTED, Broker: OPEN → valid transition
        order = _make_submitted_order("ORD001", status=OrderStatus.SUBMITTED)
        ledger = _make_ledger_with(order)
        broker = FakeBroker(orders=[_RAW_OPEN])  # status=OPEN
        service = ReconciliationService(broker, ledger)
        service.reconcile()
        # Ledger should now show OPEN
        assert ledger.get_order(order.internal_order_id).status == OrderStatus.OPEN

    def test_mismatch_count_incremented(self):
        order = _make_submitted_order("ORD001", status=OrderStatus.SUBMITTED)
        ledger = _make_ledger_with(order)
        broker = FakeBroker(orders=[_RAW_OPEN])
        report = ReconciliationService(broker, ledger).reconcile()
        assert report.status_mismatches == 1

    def test_status_mismatch_updated_discrepancy_recorded(self):
        order = _make_submitted_order("ORD001", status=OrderStatus.SUBMITTED)
        ledger = _make_ledger_with(order)
        broker = FakeBroker(orders=[_RAW_OPEN])
        report = ReconciliationService(broker, ledger).reconcile()
        codes = [d.code for d in report.discrepancies]
        assert CODE_STATUS_MISMATCH_UPDATED in codes

    def test_status_mismatch_updated_is_low_severity(self):
        order = _make_submitted_order("ORD001", status=OrderStatus.SUBMITTED)
        ledger = _make_ledger_with(order)
        broker = FakeBroker(orders=[_RAW_OPEN])
        report = ReconciliationService(broker, ledger).reconcile()
        d = next(x for x in report.discrepancies if x.code == CODE_STATUS_MISMATCH_UPDATED)
        assert d.severity == SEVERITY_LOW

    def test_valid_mismatch_success_remains_true(self):
        order = _make_submitted_order("ORD001", status=OrderStatus.SUBMITTED)
        ledger = _make_ledger_with(order)
        broker = FakeBroker(orders=[_RAW_OPEN])
        report = ReconciliationService(broker, ledger).reconcile()
        assert report.success is True

    def test_submitted_to_filled_via_broker(self):
        order = _make_submitted_order("ORD001", status=OrderStatus.SUBMITTED)
        ledger = _make_ledger_with(order)
        broker = FakeBroker(orders=[_RAW_COMPLETE])  # status=COMPLETE → FILLED
        service = ReconciliationService(broker, ledger)
        service.reconcile()
        assert ledger.get_order(order.internal_order_id).status == OrderStatus.FILLED


# ---------------------------------------------------------------------------
# Tests: status mismatch — invalid transition
# ---------------------------------------------------------------------------


class TestStatusMismatchInvalidTransition:
    def test_invalid_transition_records_discrepancy(self):
        # FILLED → OPEN is invalid; state machine will raise
        order = _make_submitted_order("ORD001", status=OrderStatus.FILLED)
        ledger = _make_ledger_with(order)
        broker = FakeBroker(orders=[_RAW_OPEN])  # broker says OPEN but ledger is FILLED
        report = ReconciliationService(broker, ledger).reconcile()
        codes = [d.code for d in report.discrepancies]
        assert CODE_INVALID_TRANSITION in codes

    def test_invalid_transition_is_high_severity(self):
        order = _make_submitted_order("ORD001", status=OrderStatus.FILLED)
        ledger = _make_ledger_with(order)
        broker = FakeBroker(orders=[_RAW_OPEN])
        report = ReconciliationService(broker, ledger).reconcile()
        d = next(x for x in report.discrepancies if x.code == CODE_INVALID_TRANSITION)
        assert d.severity == SEVERITY_HIGH

    def test_invalid_transition_success_false(self):
        order = _make_submitted_order("ORD001", status=OrderStatus.FILLED)
        ledger = _make_ledger_with(order)
        broker = FakeBroker(orders=[_RAW_OPEN])
        report = ReconciliationService(broker, ledger).reconcile()
        assert report.success is False

    def test_ledger_not_mutated_on_invalid_transition(self):
        order = _make_submitted_order("ORD001", status=OrderStatus.FILLED)
        ledger = _make_ledger_with(order)
        broker = FakeBroker(orders=[_RAW_OPEN])
        ReconciliationService(broker, ledger).reconcile()
        # Status should remain FILLED (transition was rejected)
        assert ledger.get_order(order.internal_order_id).status == OrderStatus.FILLED


# ---------------------------------------------------------------------------
# Tests: mapping error
# ---------------------------------------------------------------------------


class TestMappingError:
    def test_unmappable_broker_order_records_discrepancy(self):
        broker = FakeBroker(orders=[_RAW_BAD])
        report = ReconciliationService(broker, OrderLedger()).reconcile()
        codes = [d.code for d in report.discrepancies]
        assert CODE_MAPPING_ERROR in codes

    def test_mapping_error_is_medium_severity(self):
        broker = FakeBroker(orders=[_RAW_BAD])
        report = ReconciliationService(broker, OrderLedger()).reconcile()
        d = next(x for x in report.discrepancies if x.code == CODE_MAPPING_ERROR)
        assert d.severity == SEVERITY_MEDIUM

    def test_mapping_error_does_not_crash_reconciliation(self):
        # Mix of good and bad orders
        broker = FakeBroker(orders=[_RAW_BAD, _RAW_UNKNOWN_SYMBOL])
        report = ReconciliationService(broker, OrderLedger()).reconcile()
        # Bad order → mapping error; good order → unknown
        assert any(d.code == CODE_MAPPING_ERROR for d in report.discrepancies)
        assert any(d.code == CODE_UNKNOWN_BROKER_ORDER for d in report.discrepancies)


# ---------------------------------------------------------------------------
# Tests: positions
# ---------------------------------------------------------------------------


class TestReconcilePositions:
    def test_position_count_in_report(self):
        broker = FakeBroker(positions=[_FAKE_POSITION])
        report = ReconciliationService(broker, OrderLedger()).reconcile()
        assert report.broker_position_count == 1

    def test_empty_positions(self):
        report = ReconciliationService(FakeBroker(), OrderLedger()).reconcile()
        assert report.broker_position_count == 0

    def test_positions_dict_format_handled(self):
        # Zerodha real format: {"net": [...], "day": [...]}
        class DictPositionBroker(FakeBroker):
            def get_positions(self) -> dict:
                return {"net": [_FAKE_POSITION], "day": []}

        report = ReconciliationService(DictPositionBroker(), OrderLedger()).reconcile()
        assert report.broker_position_count == 1


# ---------------------------------------------------------------------------
# Tests: broker placement methods not called
# ---------------------------------------------------------------------------


class TestNoBrokerMutation:
    def test_place_order_never_called(self):
        order = _make_submitted_order("ORD001")
        ledger = _make_ledger_with(order)
        # FakeBroker.place_order raises AssertionError if called.
        # If reconcile() calls it, the test will fail.
        broker = FakeBroker(orders=[_RAW_OPEN])
        ReconciliationService(broker, ledger).reconcile()  # must not raise

    def test_multiple_orders_no_broker_mutation(self):
        o1 = _make_open_order("ORD001")
        o2 = _make_submitted_order("ORD002", status=OrderStatus.SUBMITTED)
        ledger = _make_ledger_with(o1, o2)
        broker = FakeBroker(
            orders=[_RAW_OPEN, {**_RAW_OPEN, "order_id": "ORD002", "status": "OPEN"}]
        )
        ReconciliationService(broker, ledger).reconcile()  # must not raise
