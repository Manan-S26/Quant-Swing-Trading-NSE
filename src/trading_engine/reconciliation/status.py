"""Lightweight status page for the trading session.

A pure data object (no Streamlit, no Flask) that collects session metrics
from the OrderLedger and the most recent ReconciliationReport into a
JSON-serialisable dict.  A future dashboard milestone can consume this.
"""

from __future__ import annotations

from typing import Any

from trading_engine.domain.models import Position
from trading_engine.execution.ledger import OrderLedger
from trading_engine.reconciliation.models import ReconciliationReport


class StatusPage:
    """Snapshot of the current trading session state.

    Args:
        ledger:                    The session OrderLedger.
        last_reconciliation_report: Most recent ReconciliationReport (or None).
        broker_positions:           Current broker positions list (or None).
    """

    def __init__(
        self,
        ledger: OrderLedger,
        last_reconciliation_report: ReconciliationReport | None = None,
        broker_positions: list[Position] | list[dict[str, Any]] | None = None,
    ) -> None:
        self._ledger = ledger
        self._last_report = last_reconciliation_report
        self._broker_positions = broker_positions or []

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable status dict.

        Keys:
            orders_by_status:              Counts of orders grouped by status string.
            total_orders:                  Total orders in the ledger.
            total_fills:                   Total fills in the ledger.
            total_risk_decisions:          Total risk decisions in the ledger.
            open_positions_count:          Number of broker positions (from last reconciliation
                                           or broker_positions constructor arg).
            last_reconciliation_timestamp: ISO-8601 string or None.
            last_reconciliation_success:   bool or None.
            discrepancy_count:             Number of discrepancies in last report (0 if no report).
        """
        orders = self._ledger.list_orders()

        # Group by status
        orders_by_status: dict[str, int] = {}
        for order in orders:
            key = str(order.status)
            orders_by_status[key] = orders_by_status.get(key, 0) + 1

        # Reconciliation info
        last_ts: str | None = None
        last_success: bool | None = None
        discrepancy_count = 0
        if self._last_report is not None:
            last_ts = self._last_report.reconciled_at.isoformat()
            last_success = self._last_report.success
            discrepancy_count = len(self._last_report.discrepancies)

        # Position count — prefer report count if available, else length of positions arg
        open_positions_count: int
        if self._last_report is not None:
            open_positions_count = self._last_report.broker_position_count
        else:
            open_positions_count = len(self._broker_positions)

        return {
            "orders_by_status": orders_by_status,
            "total_orders": len(orders),
            "total_fills": len(self._ledger.list_fills()),
            "total_risk_decisions": len(self._ledger.list_risk_decisions()),
            "open_positions_count": open_positions_count,
            "last_reconciliation_timestamp": last_ts,
            "last_reconciliation_success": last_success,
            "discrepancy_count": discrepancy_count,
        }
