"""Domain models for the live execution safety layer.

Defines approval modes, approval statuses, and the request/decision dataclasses
used by the approval gate and audit logger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from trading_engine.domain.enums import OrderType, ProductType, Side


class ApprovalMode(StrEnum):
    """Determines how the LiveOrderApprovalGate handles incoming OrderIntents.

    AUTO_PAPER     — Automatically approves in paper/dry-run contexts only.
                     Does NOT imply real execution.
    MANUAL_APPROVE — Each intent must be explicitly approved by an operator.
                     Raises ManualApprovalRequired until the operator acts.
    AUTO_LIVE      — Reserved for future live execution.  Raises SafetyError
                     in this milestone.  Do not use for real orders yet.
    """

    AUTO_PAPER = "auto_paper"
    MANUAL_APPROVE = "manual_approve"
    AUTO_LIVE = "auto_live"


class ApprovalStatus(StrEnum):
    """Lifecycle state of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    AUTO_REJECTED = "auto_rejected"  # Rejected automatically (e.g. risk engine block)


@dataclass
class ApprovalRequest:
    """A request for operator or automated approval of an order intent.

    Fields:
        approval_id:     Unique ID for this request.
        created_at:      When the request was created.
        expires_at:      Optional expiry time; None = no expiry.
        strategy_id:     Strategy that generated the underlying OrderIntent.
        symbol:          Trading symbol.
        side:            BUY or SELL.
        quantity:        Number of shares.  Must be positive.
        order_type:      MARKET, LIMIT, SL, or SL-M.
        product:         MIS, CNC, or NRML.
        estimated_price: Indicative fill price, if known.
        reason:          Human-readable context for the request.
        raw_intent:      Serialised OrderIntent for audit purposes.

    Validation:
        - approval_id must not be empty.
        - quantity must be positive.
        - expires_at, if provided, must be strictly after created_at.
    """

    approval_id: str
    created_at: datetime
    expires_at: datetime | None
    strategy_id: str
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType
    product: ProductType
    estimated_price: Decimal | None = None
    reason: str | None = None
    raw_intent: dict[str, Any] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.approval_id.strip():
            raise ValueError("ApprovalRequest.approval_id cannot be empty.")
        if self.quantity <= 0:
            raise ValueError(f"ApprovalRequest.quantity must be positive, got {self.quantity}")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("ApprovalRequest.expires_at must be strictly after created_at.")

    def is_expired(self, now: datetime | None = None) -> bool:
        """Return True if this request has passed its expiry time."""
        if self.expires_at is None:
            return False
        check_time = now or datetime.now(tz=UTC)
        # If expires_at is naive, compare naively; if aware, compare aware.
        if self.expires_at.tzinfo is not None and check_time.tzinfo is None:
            check_time = datetime.now(tz=UTC)
        elif self.expires_at.tzinfo is None and check_time.tzinfo is not None:
            check_time = datetime.utcnow()  # noqa: DTZ003 — intentional naive comparison
        return check_time >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "side": str(self.side),
            "quantity": self.quantity,
            "order_type": str(self.order_type),
            "product": str(self.product),
            "estimated_price": str(self.estimated_price) if self.estimated_price else None,
            "reason": self.reason,
        }


@dataclass
class ApprovalDecision:
    """An operator's (or system's) verdict on an ApprovalRequest.

    Fields:
        approval_id: Links back to the ApprovalRequest.
        status:      The decision outcome.
        decided_at:  When the decision was made.
        decided_by:  Identifier of who/what made the decision.
        reason:      Optional explanation for the decision.

    Validation:
        - approval_id must not be empty.
    """

    approval_id: str
    status: ApprovalStatus
    decided_at: datetime
    decided_by: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.approval_id.strip():
            raise ValueError("ApprovalDecision.approval_id cannot be empty.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "status": str(self.status),
            "decided_at": self.decided_at.isoformat(),
            "decided_by": self.decided_by,
            "reason": self.reason,
        }
