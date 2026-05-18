"""Read-only broker reconciliation package.

Compares broker-reported order state against the in-memory OrderLedger and
updates ledger state where valid transitions exist.  Never modifies broker
state (no place_order / modify_order / cancel_order calls).
"""

from __future__ import annotations
