"""Tests for live_execution.audit — ApprovalAuditLogger."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from trading_engine.domain.enums import OrderType, ProductType, Side
from trading_engine.live_execution.approvals import LiveOrderApprovalGate
from trading_engine.live_execution.audit import ApprovalAuditLogger
from trading_engine.live_execution.dry_run import DryRunExecutor
from trading_engine.live_execution.models import (
    ApprovalDecision,
    ApprovalMode,
    ApprovalRequest,
    ApprovalStatus,
)
from trading_engine.strategy.signals import OrderIntent

_NOW = datetime(2024, 1, 15, 9, 30, 0, tzinfo=UTC)
_LATER = datetime(2024, 1, 15, 9, 31, 0, tzinfo=UTC)
_INTENT = OrderIntent(
    strategy_id="orb_v1",
    symbol="RELIANCE",
    exchange="NSE",
    side="BUY",
    quantity=1,
    order_type="MARKET",
    product="MIS",
)


def _make_request() -> ApprovalRequest:
    return ApprovalRequest(
        approval_id="req-audit-001",
        created_at=_NOW,
        expires_at=_LATER,
        strategy_id="orb_v1",
        symbol="RELIANCE",
        side=Side.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
        product=ProductType.MIS,
    )


def _make_decision() -> ApprovalDecision:
    return ApprovalDecision(
        approval_id="req-audit-001",
        status=ApprovalStatus.APPROVED,
        decided_at=_NOW,
        decided_by="operator",
        reason="looks good",
    )


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# log_request
# ---------------------------------------------------------------------------


class TestLogRequest:
    def test_creates_file(self, tmp_path):
        audit_file = tmp_path / "audit.jsonl"
        logger = ApprovalAuditLogger(audit_file)
        logger.log_request(_make_request())
        assert audit_file.exists()

    def test_writes_one_line(self, tmp_path):
        audit_file = tmp_path / "audit.jsonl"
        logger = ApprovalAuditLogger(audit_file)
        logger.log_request(_make_request())
        lines = _read_lines(audit_file)
        assert len(lines) == 1

    def test_event_type_is_approval_request(self, tmp_path):
        audit_file = tmp_path / "audit.jsonl"
        logger = ApprovalAuditLogger(audit_file)
        logger.log_request(_make_request())
        record = _read_lines(audit_file)[0]
        assert record["event"] == "approval_request"

    def test_approval_id_in_record(self, tmp_path):
        audit_file = tmp_path / "audit.jsonl"
        logger = ApprovalAuditLogger(audit_file)
        logger.log_request(_make_request())
        record = _read_lines(audit_file)[0]
        assert record["approval_id"] == "req-audit-001"

    def test_logged_at_present(self, tmp_path):
        audit_file = tmp_path / "audit.jsonl"
        logger = ApprovalAuditLogger(audit_file)
        logger.log_request(_make_request())
        record = _read_lines(audit_file)[0]
        assert "logged_at" in record


# ---------------------------------------------------------------------------
# log_decision
# ---------------------------------------------------------------------------


class TestLogDecision:
    def test_writes_decision_line(self, tmp_path):
        audit_file = tmp_path / "audit.jsonl"
        logger = ApprovalAuditLogger(audit_file)
        logger.log_decision(_make_decision())
        lines = _read_lines(audit_file)
        assert len(lines) == 1

    def test_event_type_is_approval_decision(self, tmp_path):
        audit_file = tmp_path / "audit.jsonl"
        logger = ApprovalAuditLogger(audit_file)
        logger.log_decision(_make_decision())
        record = _read_lines(audit_file)[0]
        assert record["event"] == "approval_decision"

    def test_status_in_record(self, tmp_path):
        audit_file = tmp_path / "audit.jsonl"
        logger = ApprovalAuditLogger(audit_file)
        logger.log_decision(_make_decision())
        record = _read_lines(audit_file)[0]
        assert record["status"] == "approved"


# ---------------------------------------------------------------------------
# log_dry_run
# ---------------------------------------------------------------------------


class TestLogDryRun:
    def test_writes_dry_run_line(self, tmp_path):
        audit_file = tmp_path / "audit.jsonl"
        logger = ApprovalAuditLogger(audit_file)
        gate = LiveOrderApprovalGate(mode=ApprovalMode.AUTO_PAPER)
        executor = DryRunExecutor(approval_gate=gate)
        preview = executor.preview(_INTENT, estimated_price=Decimal("2345"))
        logger.log_dry_run(preview)
        lines = _read_lines(audit_file)
        assert len(lines) == 1

    def test_event_type_is_dry_run(self, tmp_path):
        audit_file = tmp_path / "audit.jsonl"
        logger = ApprovalAuditLogger(audit_file)
        executor = DryRunExecutor()
        preview = executor.preview(_INTENT)
        logger.log_dry_run(preview)
        record = _read_lines(audit_file)[0]
        assert record["event"] == "dry_run_preview"


# ---------------------------------------------------------------------------
# Multiple records
# ---------------------------------------------------------------------------


class TestMultipleRecords:
    def test_appends_records(self, tmp_path):
        audit_file = tmp_path / "audit.jsonl"
        logger = ApprovalAuditLogger(audit_file)
        logger.log_request(_make_request())
        logger.log_decision(_make_decision())
        lines = _read_lines(audit_file)
        assert len(lines) == 2

    def test_records_in_order(self, tmp_path):
        audit_file = tmp_path / "audit.jsonl"
        logger = ApprovalAuditLogger(audit_file)
        logger.log_request(_make_request())
        logger.log_decision(_make_decision())
        lines = _read_lines(audit_file)
        assert lines[0]["event"] == "approval_request"
        assert lines[1]["event"] == "approval_decision"


# ---------------------------------------------------------------------------
# Parent directory creation
# ---------------------------------------------------------------------------


class TestParentDirCreation:
    def test_creates_nested_dirs(self, tmp_path):
        audit_file = tmp_path / "data" / "audit" / "approvals.jsonl"
        logger = ApprovalAuditLogger(audit_file)
        logger.log_request(_make_request())
        assert audit_file.exists()
