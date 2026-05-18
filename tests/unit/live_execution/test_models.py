"""Tests for live_execution.models — ApprovalRequest and ApprovalDecision."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trading_engine.domain.enums import OrderType, ProductType, Side
from trading_engine.live_execution.models import (
    ApprovalDecision,
    ApprovalMode,
    ApprovalRequest,
    ApprovalStatus,
)

_NOW = datetime(2024, 1, 15, 9, 30, 0, tzinfo=UTC)
_LATER = _NOW + timedelta(seconds=60)


def _make_request(**kwargs) -> ApprovalRequest:
    defaults = dict(
        approval_id="req-001",
        created_at=_NOW,
        expires_at=_LATER,
        strategy_id="orb_v1",
        symbol="RELIANCE",
        side=Side.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
        product=ProductType.MIS,
    )
    defaults.update(kwargs)
    return ApprovalRequest(**defaults)


def _make_decision(**kwargs) -> ApprovalDecision:
    defaults = dict(
        approval_id="req-001",
        status=ApprovalStatus.APPROVED,
        decided_at=_NOW,
    )
    defaults.update(kwargs)
    return ApprovalDecision(**defaults)


# ---------------------------------------------------------------------------
# ApprovalMode
# ---------------------------------------------------------------------------


class TestApprovalMode:
    def test_values_exist(self):
        assert ApprovalMode.AUTO_PAPER == "auto_paper"
        assert ApprovalMode.MANUAL_APPROVE == "manual_approve"
        assert ApprovalMode.AUTO_LIVE == "auto_live"

    def test_all_three_members(self):
        assert len(ApprovalMode) == 3


# ---------------------------------------------------------------------------
# ApprovalStatus
# ---------------------------------------------------------------------------


class TestApprovalStatus:
    def test_all_five_members(self):
        statuses = {
            ApprovalStatus.PENDING,
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.EXPIRED,
            ApprovalStatus.AUTO_REJECTED,
        }
        assert len(statuses) == 5


# ---------------------------------------------------------------------------
# ApprovalRequest validation
# ---------------------------------------------------------------------------


class TestApprovalRequestValidation:
    def test_valid_request_created(self):
        req = _make_request()
        assert req.approval_id == "req-001"
        assert req.quantity == 1

    def test_empty_approval_id_raises(self):
        with pytest.raises(ValueError, match="approval_id"):
            _make_request(approval_id="")

    def test_whitespace_approval_id_raises(self):
        with pytest.raises(ValueError, match="approval_id"):
            _make_request(approval_id="   ")

    def test_zero_quantity_raises(self):
        with pytest.raises(ValueError, match="quantity"):
            _make_request(quantity=0)

    def test_negative_quantity_raises(self):
        with pytest.raises(ValueError, match="quantity"):
            _make_request(quantity=-5)

    def test_expires_at_equal_to_created_raises(self):
        with pytest.raises(ValueError, match="expires_at"):
            _make_request(expires_at=_NOW)

    def test_expires_at_before_created_raises(self):
        with pytest.raises(ValueError, match="expires_at"):
            _make_request(expires_at=_NOW - timedelta(seconds=1))

    def test_expires_at_none_allowed(self):
        req = _make_request(expires_at=None)
        assert req.expires_at is None

    def test_optional_fields_default_none(self):
        req = _make_request()
        assert req.estimated_price is None
        assert req.reason is None
        assert req.raw_intent is None

    def test_is_expired_no_expiry(self):
        req = _make_request(expires_at=None)
        assert req.is_expired() is False

    def test_is_expired_future_expiry(self):
        req = _make_request(expires_at=_NOW + timedelta(hours=1))
        assert req.is_expired(now=_NOW) is False

    def test_is_expired_past_expiry(self):
        req = _make_request(expires_at=_NOW + timedelta(seconds=1))
        assert req.is_expired(now=_NOW + timedelta(seconds=2)) is True

    def test_to_dict_contains_required_keys(self):
        req = _make_request()
        d = req.to_dict()
        assert "approval_id" in d
        assert "symbol" in d
        assert "side" in d
        assert "quantity" in d
        assert "order_type" in d
        assert "created_at" in d


# ---------------------------------------------------------------------------
# ApprovalDecision validation
# ---------------------------------------------------------------------------


class TestApprovalDecisionValidation:
    def test_valid_decision_created(self):
        dec = _make_decision()
        assert dec.status == ApprovalStatus.APPROVED

    def test_empty_approval_id_raises(self):
        with pytest.raises(ValueError, match="approval_id"):
            _make_decision(approval_id="")

    def test_optional_fields_default_none(self):
        dec = _make_decision()
        assert dec.decided_by is None
        assert dec.reason is None

    def test_to_dict_contains_required_keys(self):
        dec = _make_decision(decided_by="operator", reason="looks good")
        d = dec.to_dict()
        assert d["approval_id"] == "req-001"
        assert d["status"] == "approved"
        assert d["decided_by"] == "operator"
        assert d["reason"] == "looks good"

    def test_rejected_decision(self):
        dec = _make_decision(status=ApprovalStatus.REJECTED, reason="too large")
        assert dec.status == ApprovalStatus.REJECTED
        assert dec.reason == "too large"
