"""Read-only broker reconciliation service.

Compares the in-memory OrderLedger against live broker state and updates
ledger order statuses where valid transitions exist.

Design (Approach B):
  - ZerodhaBroker is left unchanged; it returns raw Zerodha dicts.
  - ReconciliationService applies mapper functions internally.
  - Broker state is never modified (no place_order / modify_order / cancel_order).

Reconciliation steps:
  1. Fetch raw orders from broker, map to InternalOrder via map_zerodha_order().
  2. Build a broker-order index keyed by broker_order_id.
  3. Build a ledger-order index keyed by broker_order_id (for ledger orders
     that already have a broker_order_id assigned).
  4. For each ledger order with a broker_order_id:
       a. Not found in broker   → HIGH discrepancy (MISSING_IN_BROKER).
       b. Found, same status    → matched (no action needed).
       c. Found, diff status    → try update_order_status via ledger/state machine.
            - Valid transition  → update ledger, LOW discrepancy (STATUS_MISMATCH_UPDATED).
            - Invalid transition→ HIGH discrepancy (INVALID_TRANSITION).
  5. For each broker order not matched to a ledger order → MEDIUM discrepancy
     (UNKNOWN_BROKER_ORDER).
  6. Fetch broker positions for count only (no mutation).
  7. Return ReconciliationReport.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from trading_engine.broker.zerodha.mappers import map_zerodha_order, map_zerodha_position
from trading_engine.common.exceptions import BrokerMappingError, OrderStateTransitionError
from trading_engine.domain.models import InternalOrder, Position
from trading_engine.execution.ledger import OrderLedger
from trading_engine.reconciliation.models import (
    CODE_INVALID_TRANSITION,
    CODE_MAPPING_ERROR,
    CODE_MISSING_IN_BROKER,
    CODE_STATUS_MISMATCH_UPDATED,
    CODE_UNKNOWN_BROKER_ORDER,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    ReconciliationDiscrepancy,
    ReconciliationReport,
)


class ReconciliationService:
    """Compare broker order state against the in-memory OrderLedger.

    Args:
        broker:  Any object with get_orders() and get_positions() methods
                 that return raw Zerodha-like dicts.  ZerodhaBroker is the
                 primary implementation; fakes are used in tests.
        ledger:  The session OrderLedger.
        logger:  Optional logger; defaults to module logger.
    """

    def __init__(
        self,
        broker: Any,
        ledger: OrderLedger,
        logger: logging.Logger | None = None,
    ) -> None:
        self._broker = broker
        self._ledger = ledger
        self._log = logger or logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def reconcile(self) -> ReconciliationReport:
        """Run a full reconciliation and return the report."""
        return self.reconcile_orders()

    def reconcile_orders(self) -> ReconciliationReport:
        """Reconcile broker orders against ledger orders.

        Returns:
            ReconciliationReport with counts and any discrepancies found.
        """
        reconciled_at = datetime.now()
        discrepancies: list[ReconciliationDiscrepancy] = []

        # ------------------------------------------------------------------
        # 1. Fetch and map broker orders
        # ------------------------------------------------------------------
        raw_orders: list[dict[str, Any]] = self._fetch_broker_orders()
        broker_orders: list[InternalOrder] = []
        for raw in raw_orders:
            try:
                broker_orders.append(map_zerodha_order(raw))
            except BrokerMappingError as exc:
                self._log.warning("Reconcile: mapping error for raw order %s: %s", raw, exc)
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        code=CODE_MAPPING_ERROR,
                        message=str(exc),
                        severity=SEVERITY_MEDIUM,
                        broker_order_id=raw.get("order_id"),
                        symbol=raw.get("tradingsymbol"),
                    )
                )

        # Index broker orders by broker_order_id (skip None)
        broker_by_id: dict[str, InternalOrder] = {
            o.broker_order_id: o for o in broker_orders if o.broker_order_id is not None
        }

        # ------------------------------------------------------------------
        # 2. Fetch broker positions (count only in this milestone)
        # ------------------------------------------------------------------
        broker_positions = self.reconcile_positions()
        broker_position_count = len(broker_positions)

        # ------------------------------------------------------------------
        # 3. Compare ledger orders to broker orders
        # ------------------------------------------------------------------
        ledger_orders = self._ledger.list_orders()
        matched_ids: set[str] = set()  # broker_order_ids that matched
        matched_count = 0
        missing_in_broker = 0
        status_mismatches = 0

        for ledger_order in ledger_orders:
            bid = ledger_order.broker_order_id
            if bid is None:
                # No broker_order_id yet — order hasn't been submitted; skip.
                continue

            if bid not in broker_by_id:
                # Broker doesn't know this order (or it's from a different day).
                missing_in_broker += 1
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        code=CODE_MISSING_IN_BROKER,
                        message=(
                            f"Ledger order {ledger_order.internal_order_id!r} "
                            f"(broker_order_id={bid!r}) not found in broker response."
                        ),
                        severity=SEVERITY_HIGH,
                        internal_order_id=ledger_order.internal_order_id,
                        broker_order_id=bid,
                        symbol=ledger_order.symbol,
                        expected_status=ledger_order.status,
                    )
                )
                continue

            broker_order = broker_by_id[bid]
            matched_ids.add(bid)
            matched_count += 1

            # Check for status mismatch.
            if ledger_order.status == broker_order.status:
                continue  # Fully in sync.

            # Statuses differ — try to update the ledger.
            status_mismatches += 1
            try:
                self._ledger.update_order_status(
                    ledger_order.internal_order_id,
                    broker_order.status,
                    raw_broker_response=broker_order.raw_broker_response,
                )
                self._log.info(
                    "Reconcile: updated order %s: %s → %s",
                    ledger_order.internal_order_id,
                    ledger_order.status,
                    broker_order.status,
                )
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        code=CODE_STATUS_MISMATCH_UPDATED,
                        message=(
                            f"Order {ledger_order.internal_order_id!r} status updated "
                            f"{ledger_order.status!r} → {broker_order.status!r}."
                        ),
                        severity=SEVERITY_LOW,
                        internal_order_id=ledger_order.internal_order_id,
                        broker_order_id=bid,
                        symbol=ledger_order.symbol,
                        expected_status=ledger_order.status,
                        actual_status=broker_order.status,
                    )
                )
            except OrderStateTransitionError as exc:
                self._log.warning(
                    "Reconcile: invalid transition for order %s (%s → %s): %s",
                    ledger_order.internal_order_id,
                    ledger_order.status,
                    broker_order.status,
                    exc,
                )
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        code=CODE_INVALID_TRANSITION,
                        message=(
                            f"Cannot transition order {ledger_order.internal_order_id!r} "
                            f"from {ledger_order.status!r} to {broker_order.status!r}: {exc}"
                        ),
                        severity=SEVERITY_HIGH,
                        internal_order_id=ledger_order.internal_order_id,
                        broker_order_id=bid,
                        symbol=ledger_order.symbol,
                        expected_status=ledger_order.status,
                        actual_status=broker_order.status,
                    )
                )

        # ------------------------------------------------------------------
        # 4. Detect broker orders unknown to the ledger
        # ------------------------------------------------------------------
        unknown_broker_orders = 0
        for bid, broker_order in broker_by_id.items():
            if bid not in matched_ids:
                unknown_broker_orders += 1
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        code=CODE_UNKNOWN_BROKER_ORDER,
                        message=(
                            f"Broker order {bid!r} ({broker_order.symbol}) "
                            f"has no matching ledger entry."
                        ),
                        severity=SEVERITY_MEDIUM,
                        broker_order_id=bid,
                        symbol=broker_order.symbol,
                        actual_status=broker_order.status,
                    )
                )

        report = ReconciliationReport(
            reconciled_at=reconciled_at,
            broker_order_count=len(broker_orders),
            ledger_order_count=len(ledger_orders),
            broker_position_count=broker_position_count,
            matched_orders=matched_count,
            missing_in_broker=missing_in_broker,
            unknown_broker_orders=unknown_broker_orders,
            status_mismatches=status_mismatches,
            discrepancies=discrepancies,
        )
        self._log.info(
            "Reconcile: done — %d broker orders, %d ledger orders, "
            "%d matched, %d missing, %d unknown, %d mismatches, success=%s",
            report.broker_order_count,
            report.ledger_order_count,
            report.matched_orders,
            report.missing_in_broker,
            report.unknown_broker_orders,
            report.status_mismatches,
            report.success,
        )
        return report

    def reconcile_positions(self) -> list[Position]:
        """Fetch and map broker positions.

        Returns a list of ``Position`` objects mapped from the broker's net
        positions.  The ledger is not mutated — position data is used only
        for the status page and report counts in this milestone.
        """
        try:
            raw = self._broker.get_positions()
        except Exception as exc:
            self._log.warning("Reconcile: could not fetch positions: %s", exc)
            return []

        # Zerodha returns {"net": [...], "day": [...]}.
        # A fake broker in tests may return a plain list.
        if isinstance(raw, dict):
            position_list: list[dict[str, Any]] = raw.get("net", [])
        elif isinstance(raw, list):
            position_list = raw
        else:
            return []

        positions: list[Position] = []
        fetched_at = datetime.now()
        for raw_pos in position_list:
            try:
                positions.append(map_zerodha_position(raw_pos, fetched_at=fetched_at))
            except BrokerMappingError as exc:
                self._log.warning("Reconcile: could not map position %s: %s", raw_pos, exc)
        return positions

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _fetch_broker_orders(self) -> list[dict[str, Any]]:
        try:
            result = self._broker.get_orders()
            return result if isinstance(result, list) else []
        except Exception as exc:
            self._log.warning("Reconcile: could not fetch broker orders: %s", exc)
            return []
