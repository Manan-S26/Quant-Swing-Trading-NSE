"""Approval gate for live order intents.

LiveOrderApprovalGate intercepts OrderIntent objects before any order-placement
path and either:
  - AUTO_PAPER:     Automatically approves (paper/dry-run only; no real orders).
  - MANUAL_APPROVE: Creates a pending request and raises ManualApprovalRequired.
  - AUTO_LIVE:      Raises SafetyError — not implemented in this milestone.

No orders are placed. No Zerodha APIs are called.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from trading_engine.common.exceptions import ManualApprovalRequired, SafetyError
from trading_engine.domain.enums import OrderType, ProductType, Side
from trading_engine.live_execution.models import (
    ApprovalDecision,
    ApprovalMode,
    ApprovalRequest,
    ApprovalStatus,
)
from trading_engine.strategy.signals import OrderIntent


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def _intent_to_request(
    intent: OrderIntent,
    estimated_price: Any | None,
    reason: str | None,
    default_timeout_seconds: int,
) -> ApprovalRequest:
    """Build an ApprovalRequest from an OrderIntent."""
    now = _now_utc()
    expires_at = now + timedelta(seconds=default_timeout_seconds)
    return ApprovalRequest(
        approval_id=str(uuid.uuid4()),
        created_at=now,
        expires_at=expires_at,
        strategy_id=intent.strategy_id,
        symbol=intent.symbol,
        side=Side(intent.side),
        quantity=intent.quantity,
        order_type=OrderType(intent.order_type),
        product=ProductType(intent.product),
        estimated_price=estimated_price,
        reason=reason,
        raw_intent={
            "strategy_id": intent.strategy_id,
            "symbol": intent.symbol,
            "side": intent.side,
            "quantity": intent.quantity,
            "order_type": intent.order_type,
            "product": intent.product,
            "price": str(intent.price) if intent.price is not None else None,
        },
    )


class LiveOrderApprovalGate:
    """Intercepts OrderIntents and gates them through an approval workflow.

    Args:
        mode:                    ApprovalMode controlling auto vs. manual behavior.
        default_timeout_seconds: How long a pending request remains valid.
                                 Defaults to 60 s.
        logger:                  Optional logger override.

    Approval modes:
        AUTO_PAPER     — Instant APPROVED decision; suitable for paper trading.
        MANUAL_APPROVE — Creates a PENDING request; caller must call approve()
                         or reject() before the order can proceed.  The
                         require_approval() method raises ManualApprovalRequired.
        AUTO_LIVE      — Raises SafetyError.  Not ready for real execution.
    """

    def __init__(
        self,
        mode: ApprovalMode,
        default_timeout_seconds: int = 60,
        logger: logging.Logger | None = None,
    ) -> None:
        if default_timeout_seconds <= 0:
            raise ValueError(
                f"default_timeout_seconds must be positive, got {default_timeout_seconds}"
            )
        self._mode = mode
        self._timeout = default_timeout_seconds
        self._log = logger or logging.getLogger(__name__)
        # In-memory stores.
        self._requests: dict[str, ApprovalRequest] = {}
        self._decisions: dict[str, ApprovalDecision] = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def mode(self) -> ApprovalMode:
        return self._mode

    # ------------------------------------------------------------------
    # Request creation
    # ------------------------------------------------------------------

    def create_request(
        self,
        order_intent: OrderIntent,
        estimated_price: Any | None = None,
        reason: str | None = None,
    ) -> ApprovalRequest:
        """Create and store a new ApprovalRequest for an OrderIntent.

        Does not auto-approve or reject — just stores the pending request.
        """
        req = _intent_to_request(order_intent, estimated_price, reason, self._timeout)
        self._requests[req.approval_id] = req
        self._log.info(
            "ApprovalGate: created request %s for %s %s %s",
            req.approval_id,
            req.side,
            req.quantity,
            req.symbol,
        )
        return req

    # ------------------------------------------------------------------
    # Operator decisions
    # ------------------------------------------------------------------

    def approve(
        self,
        approval_id: str,
        decided_by: str = "operator",
        reason: str | None = None,
    ) -> ApprovalDecision:
        """Approve a pending request.

        Raises:
            KeyError: if the approval_id is not found.
            ValueError: if the request is already decided or expired.
        """
        self._get_pending_request(approval_id)
        decision = ApprovalDecision(
            approval_id=approval_id,
            status=ApprovalStatus.APPROVED,
            decided_at=_now_utc(),
            decided_by=decided_by,
            reason=reason,
        )
        self._decisions[approval_id] = decision
        self._log.info("ApprovalGate: APPROVED %s by %s", approval_id, decided_by)
        return decision

    def reject(
        self,
        approval_id: str,
        decided_by: str = "operator",
        reason: str | None = None,
    ) -> ApprovalDecision:
        """Reject a pending request.

        Raises:
            KeyError: if the approval_id is not found.
            ValueError: if the request is already decided or expired.
        """
        self._get_pending_request(approval_id)
        decision = ApprovalDecision(
            approval_id=approval_id,
            status=ApprovalStatus.REJECTED,
            decided_at=_now_utc(),
            decided_by=decided_by,
            reason=reason or "Rejected by operator.",
        )
        self._decisions[approval_id] = decision
        self._log.info("ApprovalGate: REJECTED %s by %s — %s", approval_id, decided_by, reason)
        return decision

    def check_decision(self, approval_id: str) -> ApprovalDecision | None:
        """Return the current decision for an approval_id, or None if pending.

        If the request has expired and no decision exists, records and returns
        an EXPIRED decision.
        """
        if approval_id in self._decisions:
            return self._decisions[approval_id]
        req = self._requests.get(approval_id)
        if req is not None and req.is_expired():
            expired = ApprovalDecision(
                approval_id=approval_id,
                status=ApprovalStatus.EXPIRED,
                decided_at=_now_utc(),
                decided_by="system",
                reason="Request expired before a decision was made.",
            )
            self._decisions[approval_id] = expired
            return expired
        return None

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def require_approval(
        self,
        order_intent: OrderIntent,
        estimated_price: Any | None = None,
        reason: str | None = None,
    ) -> ApprovalDecision:
        """Gate an OrderIntent through the configured approval mode.

        Returns:
            ApprovalDecision with status APPROVED in AUTO_PAPER mode.

        Raises:
            SafetyError:            in AUTO_LIVE mode (not implemented yet).
            ManualApprovalRequired: in MANUAL_APPROVE mode (creates a pending
                                    request and raises; caller must poll).
        """
        if self._mode == ApprovalMode.AUTO_LIVE:
            raise SafetyError(
                "AUTO_LIVE approval mode is not implemented in this milestone. "
                "Real order execution requires an explicit future implementation. "
                "Use AUTO_PAPER for paper trading or MANUAL_APPROVE for manual review."
            )

        if self._mode == ApprovalMode.AUTO_PAPER:
            req = self.create_request(order_intent, estimated_price, reason)
            decision = ApprovalDecision(
                approval_id=req.approval_id,
                status=ApprovalStatus.APPROVED,
                decided_at=_now_utc(),
                decided_by="auto_paper",
                reason="Automatically approved for paper trading.",
            )
            self._decisions[req.approval_id] = decision
            self._log.debug(
                "ApprovalGate: AUTO_PAPER approved %s %s",
                order_intent.side,
                order_intent.symbol,
            )
            return decision

        # MANUAL_APPROVE
        req = self.create_request(order_intent, estimated_price, reason)
        raise ManualApprovalRequired(
            f"Order for {order_intent.side} {order_intent.quantity} {order_intent.symbol} "
            f"requires manual approval. approval_id={req.approval_id}",
            approval_id=req.approval_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_pending_request(self, approval_id: str) -> ApprovalRequest:
        if approval_id not in self._requests:
            raise KeyError(f"No approval request found with id={approval_id!r}")
        if approval_id in self._decisions:
            raise ValueError(
                f"Approval request {approval_id!r} is already decided "
                f"(status={self._decisions[approval_id].status})."
            )
        return self._requests[approval_id]
