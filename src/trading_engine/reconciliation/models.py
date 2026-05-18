"""Reconciliation result models.

Plain dataclasses — no Pydantic — so they serialise simply to dicts
without requiring a v2 config.  All fields are JSON-safe by design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from trading_engine.domain.enums import OrderStatus

# ---------------------------------------------------------------------------
# Severity constants — used as string literals to avoid coupling to an enum
# ---------------------------------------------------------------------------

SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"

# ---------------------------------------------------------------------------
# Discrepancy codes
# ---------------------------------------------------------------------------

CODE_MISSING_IN_BROKER = "MISSING_IN_BROKER"
CODE_UNKNOWN_BROKER_ORDER = "UNKNOWN_BROKER_ORDER"
CODE_STATUS_MISMATCH_UPDATED = "STATUS_MISMATCH_UPDATED"
CODE_INVALID_TRANSITION = "INVALID_TRANSITION"
CODE_MAPPING_ERROR = "MAPPING_ERROR"


@dataclass
class ReconciliationDiscrepancy:
    """A single discrepancy detected during reconciliation.

    Attributes:
        code:               Machine-readable discrepancy code (see CODE_* constants).
        message:            Human-readable description.
        severity:           "HIGH", "MEDIUM", or "LOW".
        internal_order_id:  Engine-side order ID (if known).
        broker_order_id:    Broker-side order ID (if known).
        symbol:             Trading symbol (if known).
        expected_status:    Status the ledger held before reconciliation.
        actual_status:      Status reported by the broker.
    """

    code: str
    message: str
    severity: str
    internal_order_id: str | None = None
    broker_order_id: str | None = None
    symbol: str | None = None
    expected_status: OrderStatus | None = None
    actual_status: OrderStatus | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "internal_order_id": self.internal_order_id,
            "broker_order_id": self.broker_order_id,
            "symbol": self.symbol,
            "expected_status": str(self.expected_status) if self.expected_status else None,
            "actual_status": str(self.actual_status) if self.actual_status else None,
        }


@dataclass
class ReconciliationReport:
    """Summary of a reconciliation run.

    Attributes:
        reconciled_at:          When reconciliation ran.
        broker_order_count:     Number of orders returned by the broker.
        ledger_order_count:     Number of orders in the local ledger.
        broker_position_count:  Number of net positions returned by the broker.
        matched_orders:         Orders matched by broker_order_id.
        missing_in_broker:      Ledger orders whose broker_order_id was not
                                returned by the broker.
        unknown_broker_orders:  Broker orders with no matching ledger entry.
        status_mismatches:      Orders where statuses differed (updated or not).
        discrepancies:          Full list of discrepancy objects.
        success:                True when no HIGH-severity discrepancies exist.
    """

    reconciled_at: datetime
    broker_order_count: int = 0
    ledger_order_count: int = 0
    broker_position_count: int = 0
    matched_orders: int = 0
    missing_in_broker: int = 0
    unknown_broker_orders: int = 0
    status_mismatches: int = 0
    discrepancies: list[ReconciliationDiscrepancy] = field(default_factory=list)
    success: bool = True

    def __post_init__(self) -> None:
        # Recompute success from discrepancies when the object is constructed.
        self._recompute_success()

    def _recompute_success(self) -> None:
        self.success = not any(d.severity == SEVERITY_HIGH for d in self.discrepancies)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reconciled_at": self.reconciled_at.isoformat(),
            "broker_order_count": self.broker_order_count,
            "ledger_order_count": self.ledger_order_count,
            "broker_position_count": self.broker_position_count,
            "matched_orders": self.matched_orders,
            "missing_in_broker": self.missing_in_broker,
            "unknown_broker_orders": self.unknown_broker_orders,
            "status_mismatches": self.status_mismatches,
            "success": self.success,
            "discrepancies": [d.to_dict() for d in self.discrepancies],
        }
