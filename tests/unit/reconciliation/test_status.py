"""Tests for StatusPage."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trading_engine.domain.enums import (
    Exchange,
    OrderStatus,
    OrderType,
    ProductType,
    RiskReasonCode,
    Side,
)
from trading_engine.domain.identifiers import (
    generate_fill_id,
    generate_internal_order_id,
    generate_risk_decision_id,
)
from trading_engine.domain.models import InternalOrder, RiskDecision, TradeFill
from trading_engine.execution.ledger import OrderLedger
from trading_engine.reconciliation.models import ReconciliationReport
from trading_engine.reconciliation.status import StatusPage

_TS = datetime(2024, 1, 15, 9, 30, 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_order(
    status: OrderStatus = OrderStatus.CREATED, symbol: str = "RELIANCE"
) -> InternalOrder:
    return InternalOrder(
        internal_order_id=generate_internal_order_id(),
        strategy_id="test",
        symbol=symbol,
        exchange=Exchange.NSE,
        side=Side.BUY,
        quantity=10,
        order_type=OrderType.MARKET,
        product=ProductType.MIS,
        status=status,
        created_at=_TS,
        updated_at=_TS,
    )


def _make_fill(order: InternalOrder) -> TradeFill:
    return TradeFill(
        fill_id=generate_fill_id(),
        internal_order_id=order.internal_order_id,
        symbol=order.symbol,
        exchange=order.exchange,
        side=order.side,
        quantity=order.quantity,
        price=Decimal("2800"),
        timestamp=_TS,
    )


def _make_decision() -> RiskDecision:
    return RiskDecision(
        risk_decision_id=generate_risk_decision_id(),
        approved=True,
        reason_code=RiskReasonCode.APPROVED,
        reason_message="ok",
        timestamp=_TS,
    )


# ---------------------------------------------------------------------------
# Tests: empty ledger
# ---------------------------------------------------------------------------


class TestStatusPageEmpty:
    def test_empty_ledger_to_dict(self):
        page = StatusPage(ledger=OrderLedger())
        result = page.to_dict()
        assert result["orders_by_status"] == {}
        assert result["total_orders"] == 0
        assert result["total_fills"] == 0
        assert result["total_risk_decisions"] == 0
        assert result["open_positions_count"] == 0
        assert result["last_reconciliation_timestamp"] is None
        assert result["last_reconciliation_success"] is None
        assert result["discrepancy_count"] == 0

    def test_all_keys_present(self):
        result = StatusPage(ledger=OrderLedger()).to_dict()
        expected_keys = {
            "orders_by_status",
            "total_orders",
            "total_fills",
            "total_risk_decisions",
            "open_positions_count",
            "last_reconciliation_timestamp",
            "last_reconciliation_success",
            "discrepancy_count",
        }
        assert expected_keys == set(result.keys())


# ---------------------------------------------------------------------------
# Tests: orders grouped by status
# ---------------------------------------------------------------------------


class TestStatusPageOrderGrouping:
    def test_orders_grouped_by_status(self):
        ledger = OrderLedger()
        ledger.add_order(_make_order(OrderStatus.CREATED))
        ledger.add_order(_make_order(OrderStatus.CREATED))
        ledger.add_order(_make_order(OrderStatus.RISK_APPROVED))
        result = StatusPage(ledger=ledger).to_dict()
        assert result["orders_by_status"]["CREATED"] == 2
        assert result["orders_by_status"]["RISK_APPROVED"] == 1
        assert result["total_orders"] == 3

    def test_single_order(self):
        ledger = OrderLedger()
        ledger.add_order(_make_order(OrderStatus.FILLED))
        result = StatusPage(ledger=ledger).to_dict()
        assert result["orders_by_status"] == {"FILLED": 1}
        assert result["total_orders"] == 1

    def test_status_keys_are_strings(self):
        ledger = OrderLedger()
        ledger.add_order(_make_order(OrderStatus.SUBMITTED))
        result = StatusPage(ledger=ledger).to_dict()
        keys = list(result["orders_by_status"].keys())
        assert all(isinstance(k, str) for k in keys)


# ---------------------------------------------------------------------------
# Tests: fills and risk decisions
# ---------------------------------------------------------------------------


class TestStatusPageFilsAndDecisions:
    def test_total_fills_counted(self):
        ledger = OrderLedger()
        order = _make_order()
        ledger.add_order(order)
        ledger.add_fill(_make_fill(order))
        ledger.add_fill(_make_fill(order))
        result = StatusPage(ledger=ledger).to_dict()
        assert result["total_fills"] == 2

    def test_total_risk_decisions_counted(self):
        ledger = OrderLedger()
        ledger.add_risk_decision(_make_decision())
        result = StatusPage(ledger=ledger).to_dict()
        assert result["total_risk_decisions"] == 1


# ---------------------------------------------------------------------------
# Tests: reconciliation report integration
# ---------------------------------------------------------------------------


class TestStatusPageReconciliation:
    def test_last_reconciliation_timestamp_set(self):
        report = ReconciliationReport(reconciled_at=_TS)
        page = StatusPage(ledger=OrderLedger(), last_reconciliation_report=report)
        result = page.to_dict()
        assert result["last_reconciliation_timestamp"] == _TS.isoformat()

    def test_last_reconciliation_success_set(self):
        report = ReconciliationReport(reconciled_at=_TS)
        page = StatusPage(ledger=OrderLedger(), last_reconciliation_report=report)
        assert page.to_dict()["last_reconciliation_success"] is True

    def test_discrepancy_count_from_report(self):
        from trading_engine.reconciliation.models import SEVERITY_HIGH, ReconciliationDiscrepancy

        d = ReconciliationDiscrepancy(code="MISSING_IN_BROKER", message="m", severity=SEVERITY_HIGH)
        report = ReconciliationReport(reconciled_at=_TS, discrepancies=[d])
        page = StatusPage(ledger=OrderLedger(), last_reconciliation_report=report)
        assert page.to_dict()["discrepancy_count"] == 1

    def test_open_positions_count_from_report(self):
        report = ReconciliationReport(reconciled_at=_TS, broker_position_count=3)
        page = StatusPage(ledger=OrderLedger(), last_reconciliation_report=report)
        assert page.to_dict()["open_positions_count"] == 3

    def test_open_positions_count_from_broker_positions_arg(self):
        # No report — use broker_positions list length
        page = StatusPage(
            ledger=OrderLedger(),
            broker_positions=[{"symbol": "RELIANCE"}, {"symbol": "TCS"}],
        )
        assert page.to_dict()["open_positions_count"] == 2

    def test_no_report_timestamps_are_none(self):
        result = StatusPage(ledger=OrderLedger()).to_dict()
        assert result["last_reconciliation_timestamp"] is None
        assert result["last_reconciliation_success"] is None
