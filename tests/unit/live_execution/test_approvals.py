"""Tests for live_execution.approvals — LiveOrderApprovalGate."""

from __future__ import annotations

import pytest

from trading_engine.common.exceptions import ManualApprovalRequired, SafetyError
from trading_engine.live_execution.approvals import LiveOrderApprovalGate
from trading_engine.live_execution.models import ApprovalMode, ApprovalStatus
from trading_engine.strategy.signals import OrderIntent

_INTENT = OrderIntent(
    strategy_id="orb_v1",
    symbol="RELIANCE",
    exchange="NSE",
    side="BUY",
    quantity=1,
    order_type="MARKET",
    product="MIS",
)


def _make_gate(mode: ApprovalMode = ApprovalMode.AUTO_PAPER, timeout: int = 60):
    return LiveOrderApprovalGate(mode=mode, default_timeout_seconds=timeout)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestGateInit:
    def test_valid_construction(self):
        gate = _make_gate()
        assert gate.mode == ApprovalMode.AUTO_PAPER

    def test_zero_timeout_raises(self):
        with pytest.raises(ValueError, match="positive"):
            LiveOrderApprovalGate(mode=ApprovalMode.AUTO_PAPER, default_timeout_seconds=0)

    def test_negative_timeout_raises(self):
        with pytest.raises(ValueError, match="positive"):
            LiveOrderApprovalGate(mode=ApprovalMode.AUTO_PAPER, default_timeout_seconds=-1)


# ---------------------------------------------------------------------------
# create_request
# ---------------------------------------------------------------------------


class TestCreateRequest:
    def test_creates_request(self):
        gate = _make_gate()
        req = gate.create_request(_INTENT)
        assert req.approval_id
        assert req.symbol == "RELIANCE"
        assert req.quantity == 1

    def test_request_stored_in_gate(self):
        gate = _make_gate()
        req = gate.create_request(_INTENT)
        assert req.approval_id in gate._requests

    def test_expires_at_set(self):
        gate = _make_gate(timeout=30)
        req = gate.create_request(_INTENT)
        delta = (req.expires_at - req.created_at).total_seconds()
        assert delta == pytest.approx(30, abs=1)


# ---------------------------------------------------------------------------
# AUTO_PAPER mode
# ---------------------------------------------------------------------------


class TestAutoPaper:
    def test_require_approval_returns_approved(self):
        gate = _make_gate(ApprovalMode.AUTO_PAPER)
        decision = gate.require_approval(_INTENT)
        assert decision.status == ApprovalStatus.APPROVED

    def test_decided_by_auto_paper(self):
        gate = _make_gate(ApprovalMode.AUTO_PAPER)
        decision = gate.require_approval(_INTENT)
        assert decision.decided_by == "auto_paper"

    def test_does_not_raise(self):
        gate = _make_gate(ApprovalMode.AUTO_PAPER)
        # Should not raise ManualApprovalRequired or SafetyError.
        gate.require_approval(_INTENT)


# ---------------------------------------------------------------------------
# MANUAL_APPROVE mode
# ---------------------------------------------------------------------------


class TestManualApprove:
    def test_require_approval_raises_manual_required(self):
        gate = _make_gate(ApprovalMode.MANUAL_APPROVE)
        with pytest.raises(ManualApprovalRequired) as exc_info:
            gate.require_approval(_INTENT)
        assert exc_info.value.approval_id

    def test_request_stored_before_raise(self):
        gate = _make_gate(ApprovalMode.MANUAL_APPROVE)
        try:
            gate.require_approval(_INTENT)
        except ManualApprovalRequired as exc:
            assert exc.approval_id in gate._requests

    def test_approve_pending_request(self):
        gate = _make_gate(ApprovalMode.MANUAL_APPROVE)
        try:
            gate.require_approval(_INTENT)
        except ManualApprovalRequired as exc:
            approval_id = exc.approval_id

        decision = gate.approve(approval_id, decided_by="trader_1")
        assert decision.status == ApprovalStatus.APPROVED
        assert decision.decided_by == "trader_1"

    def test_reject_pending_request(self):
        gate = _make_gate(ApprovalMode.MANUAL_APPROVE)
        try:
            gate.require_approval(_INTENT)
        except ManualApprovalRequired as exc:
            approval_id = exc.approval_id

        decision = gate.reject(approval_id, reason="too risky")
        assert decision.status == ApprovalStatus.REJECTED
        assert decision.reason == "too risky"

    def test_approve_nonexistent_id_raises(self):
        gate = _make_gate(ApprovalMode.MANUAL_APPROVE)
        with pytest.raises(KeyError):
            gate.approve("nonexistent-id")

    def test_approve_already_decided_raises(self):
        gate = _make_gate(ApprovalMode.MANUAL_APPROVE)
        try:
            gate.require_approval(_INTENT)
        except ManualApprovalRequired as exc:
            aid = exc.approval_id
        gate.approve(aid)
        with pytest.raises(ValueError, match="already decided"):
            gate.approve(aid)


# ---------------------------------------------------------------------------
# AUTO_LIVE mode
# ---------------------------------------------------------------------------


class TestAutoLive:
    def test_require_approval_raises_safety_error(self):
        gate = _make_gate(ApprovalMode.AUTO_LIVE)
        with pytest.raises(SafetyError):
            gate.require_approval(_INTENT)

    def test_create_request_still_works(self):
        gate = _make_gate(ApprovalMode.AUTO_LIVE)
        req = gate.create_request(_INTENT)
        assert req.approval_id


# ---------------------------------------------------------------------------
# check_decision
# ---------------------------------------------------------------------------


class TestCheckDecision:
    def test_pending_request_returns_none(self):
        gate = _make_gate(ApprovalMode.MANUAL_APPROVE)
        try:
            gate.require_approval(_INTENT)
        except ManualApprovalRequired as exc:
            aid = exc.approval_id
        assert gate.check_decision(aid) is None

    def test_approved_request_returns_decision(self):
        gate = _make_gate(ApprovalMode.AUTO_PAPER)
        decision = gate.require_approval(_INTENT)
        result = gate.check_decision(decision.approval_id)
        assert result is not None
        assert result.status == ApprovalStatus.APPROVED

    def test_nonexistent_id_returns_none(self):
        gate = _make_gate()
        assert gate.check_decision("nonexistent") is None
