"""ID generation helpers for trading engine domain objects.

IDs are string-based, prefixed for readability, and generated locally using
UUID4 hex so they require no database round-trip.

Format: <prefix><16 hex chars>
Example: ord_3f2a1b9c4e8d7f06

Uniqueness guarantee: UUID4 has ~5.3 × 10^36 possible values, which is
sufficient for local use without collision risk.
"""

from __future__ import annotations

import uuid


def _make_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


def generate_internal_order_id() -> str:
    """Generate a unique internal order ID with prefix 'ord_'."""
    return _make_id("ord_")


def generate_signal_id() -> str:
    """Generate a unique signal ID with prefix 'sig_'."""
    return _make_id("sig_")


def generate_risk_decision_id() -> str:
    """Generate a unique risk decision ID with prefix 'risk_'."""
    return _make_id("risk_")


def generate_fill_id() -> str:
    """Generate a unique trade fill ID with prefix 'fill_'."""
    return _make_id("fill_")
