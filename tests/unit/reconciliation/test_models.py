"""Tests for ReconciliationDiscrepancy and ReconciliationReport models."""

from __future__ import annotations

from datetime import datetime

from trading_engine.domain.enums import OrderStatus
from trading_engine.reconciliation.models import (
    CODE_INVALID_TRANSITION,
    CODE_MISSING_IN_BROKER,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    ReconciliationDiscrepancy,
    ReconciliationReport,
)

_TS = datetime(2024, 1, 15, 9, 30, 0)


class TestReconciliationDiscrepancy:
    def test_to_dict_all_fields(self):
        d = ReconciliationDiscrepancy(
            code=CODE_MISSING_IN_BROKER,
            message="Order not in broker",
            severity=SEVERITY_HIGH,
            internal_order_id="ord_abc",
            broker_order_id="zerodha_123",
            symbol="RELIANCE",
            expected_status=OrderStatus.SUBMITTED,
            actual_status=None,
        )
        result = d.to_dict()
        assert result["code"] == CODE_MISSING_IN_BROKER
        assert result["message"] == "Order not in broker"
        assert result["severity"] == SEVERITY_HIGH
        assert result["internal_order_id"] == "ord_abc"
        assert result["broker_order_id"] == "zerodha_123"
        assert result["symbol"] == "RELIANCE"
        assert result["expected_status"] == "SUBMITTED"
        assert result["actual_status"] is None

    def test_to_dict_minimal(self):
        d = ReconciliationDiscrepancy(
            code=CODE_MISSING_IN_BROKER,
            message="missing",
            severity=SEVERITY_HIGH,
        )
        result = d.to_dict()
        assert result["internal_order_id"] is None
        assert result["broker_order_id"] is None
        assert result["expected_status"] is None

    def test_status_serialized_as_string(self):
        d = ReconciliationDiscrepancy(
            code=CODE_INVALID_TRANSITION,
            message="bad transition",
            severity=SEVERITY_HIGH,
            expected_status=OrderStatus.SUBMITTED,
            actual_status=OrderStatus.FILLED,
        )
        result = d.to_dict()
        assert result["expected_status"] == "SUBMITTED"
        assert result["actual_status"] == "FILLED"


class TestReconciliationReport:
    def test_empty_report_success_true(self):
        report = ReconciliationReport(reconciled_at=_TS)
        assert report.success is True
        assert report.discrepancies == []

    def test_success_false_when_high_discrepancy(self):
        d = ReconciliationDiscrepancy(
            code=CODE_MISSING_IN_BROKER,
            message="missing",
            severity=SEVERITY_HIGH,
        )
        report = ReconciliationReport(reconciled_at=_TS, discrepancies=[d])
        assert report.success is False

    def test_success_true_when_only_low_discrepancies(self):
        d = ReconciliationDiscrepancy(
            code="STATUS_MISMATCH_UPDATED",
            message="updated",
            severity=SEVERITY_LOW,
        )
        report = ReconciliationReport(reconciled_at=_TS, discrepancies=[d])
        assert report.success is True

    def test_to_dict_serializes_safely(self):
        report = ReconciliationReport(
            reconciled_at=_TS,
            broker_order_count=5,
            ledger_order_count=4,
            broker_position_count=2,
            matched_orders=3,
            missing_in_broker=1,
            unknown_broker_orders=2,
            status_mismatches=1,
        )
        d = report.to_dict()
        assert d["reconciled_at"] == _TS.isoformat()
        assert d["broker_order_count"] == 5
        assert d["ledger_order_count"] == 4
        assert d["broker_position_count"] == 2
        assert d["matched_orders"] == 3
        assert d["missing_in_broker"] == 1
        assert d["unknown_broker_orders"] == 2
        assert d["status_mismatches"] == 1
        assert d["success"] is True
        assert d["discrepancies"] == []

    def test_to_dict_discrepancies_serialized(self):
        d = ReconciliationDiscrepancy(
            code=CODE_MISSING_IN_BROKER, message="m", severity=SEVERITY_HIGH
        )
        report = ReconciliationReport(reconciled_at=_TS, discrepancies=[d])
        result = report.to_dict()
        assert len(result["discrepancies"]) == 1
        assert result["discrepancies"][0]["code"] == CODE_MISSING_IN_BROKER
        assert result["success"] is False

    def test_counts_default_to_zero(self):
        report = ReconciliationReport(reconciled_at=_TS)
        d = report.to_dict()
        for key in (
            "broker_order_count",
            "ledger_order_count",
            "broker_position_count",
            "matched_orders",
            "missing_in_broker",
            "unknown_broker_orders",
            "status_mismatches",
        ):
            assert d[key] == 0
