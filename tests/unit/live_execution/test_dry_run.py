"""Tests for live_execution.dry_run — DryRunExecutor and DryRunOrderPreview."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from trading_engine.domain.enums import Side
from trading_engine.live_execution.approvals import LiveOrderApprovalGate
from trading_engine.live_execution.dry_run import DryRunExecutor, DryRunOrderPreview
from trading_engine.live_execution.models import ApprovalMode, ApprovalStatus
from trading_engine.strategy.signals import OrderIntent

_INTENT = OrderIntent(
    strategy_id="test_strategy",
    symbol="RELIANCE",
    exchange="NSE",
    side="BUY",
    quantity=2,
    order_type="MARKET",
    product="MIS",
)

_PRICE = Decimal("2345.00")


# ---------------------------------------------------------------------------
# Fake RiskEngine helpers
# ---------------------------------------------------------------------------


class _FakeRiskDecision:
    def __init__(self, approved: bool):
        self.approved = approved
        self.reason_code = "APPROVED" if approved else "ORDER_VALUE_LIMIT_BREACHED"
        self.reason_message = "approved" if approved else "value too large"


class _ApprovingRiskEngine:
    def check_order_intent(self, intent, snapshot, ts):
        return _FakeRiskDecision(approved=True)


class _RejectingRiskEngine:
    def check_order_intent(self, intent, snapshot, ts):
        return _FakeRiskDecision(approved=False)


# ---------------------------------------------------------------------------
# Basic DryRunExecutor
# ---------------------------------------------------------------------------


class TestDryRunExecutorBasic:
    def test_no_risk_no_gate_returns_preview(self):
        executor = DryRunExecutor()
        preview = executor.preview(_INTENT)
        assert isinstance(preview, DryRunOrderPreview)

    def test_symbol_in_preview(self):
        executor = DryRunExecutor()
        preview = executor.preview(_INTENT)
        assert preview.symbol == "RELIANCE"

    def test_side_in_preview(self):
        executor = DryRunExecutor()
        preview = executor.preview(_INTENT)
        assert preview.side == Side.BUY

    def test_estimated_price_stored(self):
        executor = DryRunExecutor()
        preview = executor.preview(_INTENT, estimated_price=_PRICE)
        assert preview.estimated_price == _PRICE

    def test_estimated_order_value_computed(self):
        executor = DryRunExecutor()
        preview = executor.preview(_INTENT, estimated_price=_PRICE)
        assert preview.estimated_order_value == _PRICE * 2

    def test_no_broker_called(self):
        # DryRunExecutor should never touch a broker; just verify it doesn't raise.
        executor = DryRunExecutor()
        executor.preview(_INTENT)  # must not raise

    def test_generated_at_is_recent(self):
        executor = DryRunExecutor()
        preview = executor.preview(_INTENT)
        age = (datetime.now(tz=UTC) - preview.generated_at).total_seconds()
        assert age < 5

    def test_no_risk_decision_when_no_engine(self):
        executor = DryRunExecutor()
        preview = executor.preview(_INTENT)
        assert preview.risk_decision is None

    def test_no_approval_status_when_no_gate(self):
        executor = DryRunExecutor()
        preview = executor.preview(_INTENT)
        assert preview.approval_status is None


# ---------------------------------------------------------------------------
# Risk engine integration
# ---------------------------------------------------------------------------


class TestDryRunWithRisk:
    def test_approving_risk_engine(self):
        executor = DryRunExecutor(risk_engine=_ApprovingRiskEngine())

        # Risk engine needs a snapshot; use a minimal fake one.
        class _FakeSnapshot:
            pass

        preview = executor.preview(_INTENT, portfolio_snapshot=_FakeSnapshot())
        assert preview.risk_decision is not None
        assert preview.risk_decision.approved is True

    def test_rejecting_risk_engine_sets_auto_rejected(self):
        executor = DryRunExecutor(risk_engine=_RejectingRiskEngine())

        class _FakeSnapshot:
            pass

        preview = executor.preview(_INTENT, portfolio_snapshot=_FakeSnapshot())
        assert preview.approval_status == ApprovalStatus.AUTO_REJECTED

    def test_risk_rejection_message_contains_reason(self):
        executor = DryRunExecutor(risk_engine=_RejectingRiskEngine())

        class _FakeSnapshot:
            pass

        preview = executor.preview(_INTENT, portfolio_snapshot=_FakeSnapshot())
        assert "BLOCKED" in preview.message or "risk" in preview.message.lower()

    def test_no_snapshot_skips_risk_check(self):
        executor = DryRunExecutor(risk_engine=_ApprovingRiskEngine())
        preview = executor.preview(_INTENT, portfolio_snapshot=None)
        assert preview.risk_decision is None


# ---------------------------------------------------------------------------
# Approval gate integration
# ---------------------------------------------------------------------------


class TestDryRunWithApprovalGate:
    def test_auto_paper_gate_gives_approved(self):
        gate = LiveOrderApprovalGate(mode=ApprovalMode.AUTO_PAPER)
        executor = DryRunExecutor(approval_gate=gate)
        preview = executor.preview(_INTENT)
        assert preview.approval_status == ApprovalStatus.APPROVED

    def test_manual_approve_gate_gives_pending(self):
        gate = LiveOrderApprovalGate(mode=ApprovalMode.MANUAL_APPROVE)
        executor = DryRunExecutor(approval_gate=gate)
        preview = executor.preview(_INTENT)
        assert preview.approval_status == ApprovalStatus.PENDING

    def test_auto_live_gate_blocks(self):
        gate = LiveOrderApprovalGate(mode=ApprovalMode.AUTO_LIVE)
        executor = DryRunExecutor(approval_gate=gate)
        preview = executor.preview(_INTENT)
        assert preview.approval_status == ApprovalStatus.AUTO_REJECTED

    def test_risk_rejection_skips_approval(self):
        gate = LiveOrderApprovalGate(mode=ApprovalMode.AUTO_PAPER)
        executor = DryRunExecutor(
            risk_engine=_RejectingRiskEngine(),
            approval_gate=gate,
        )

        class _FakeSnapshot:
            pass

        preview = executor.preview(_INTENT, portfolio_snapshot=_FakeSnapshot())
        assert preview.approval_status == ApprovalStatus.AUTO_REJECTED


# ---------------------------------------------------------------------------
# JSON serialisation
# ---------------------------------------------------------------------------


class TestDryRunPreviewToDict:
    def test_to_dict_is_json_serialisable(self):
        executor = DryRunExecutor()
        preview = executor.preview(_INTENT, estimated_price=_PRICE)
        d = preview.to_dict()
        # Should not raise.
        json.dumps(d)

    def test_to_dict_contains_required_keys(self):
        executor = DryRunExecutor()
        preview = executor.preview(_INTENT)
        d = preview.to_dict()
        for key in ("generated_at", "symbol", "side", "quantity", "order_type", "message"):
            assert key in d

    def test_to_dict_risk_none_when_no_engine(self):
        executor = DryRunExecutor()
        preview = executor.preview(_INTENT)
        assert preview.to_dict()["risk_decision"] is None

    def test_to_dict_estimated_price_as_string(self):
        executor = DryRunExecutor()
        preview = executor.preview(_INTENT, estimated_price=_PRICE)
        d = preview.to_dict()
        assert d["estimated_price"] == str(_PRICE)
