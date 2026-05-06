"""Paper trading broker.

PaperBroker simulates broker connectivity for paper trading mode.
It never makes real network calls. Order placement methods are blocked.

Paper fill simulation (matching simulated orders against live prices) will
be implemented in Milestone 8 (Paper Trading Engine). This class only
handles the read-only interface and connection lifecycle.
"""

from __future__ import annotations

import logging
from typing import Any

from trading_engine.broker.base import Broker

logger = logging.getLogger(__name__)


class PaperBroker(Broker):
    """Simulated broker for paper trading.

    All read-only methods return safe empty/default values.
    All order placement methods raise LiveTradingDisabledError (inherited
    from the Broker base class — identical safety gate as live mode).

    This broker is safe to run in automated tests and local development
    without any Zerodha credentials.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._connected: bool = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Simulate broker connection (no-op network-wise)."""
        self._connected = True
        self._logger.info("PaperBroker: connected (simulated).")

    def disconnect(self) -> None:
        """Simulate broker disconnection."""
        self._connected = False
        self._logger.info("PaperBroker: disconnected (simulated).")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Read-only account data — all return safe empty defaults
    # ------------------------------------------------------------------

    def get_positions(self) -> list[dict[str, Any]]:
        """Return empty positions list (no real positions in paper mode)."""
        return []

    def get_orders(self) -> list[dict[str, Any]]:
        """Return empty orders list."""
        return []

    def get_trades(self) -> list[dict[str, Any]]:
        """Return empty trades list."""
        return []

    def get_margins(self) -> dict[str, Any]:
        """Return empty margins dict."""
        return {}

    # ------------------------------------------------------------------
    # Streaming — placeholder
    # ------------------------------------------------------------------

    def stream_ticks(self, symbols: list[str], callback: Any) -> None:
        """Live tick streaming is not implemented in PaperBroker yet.

        Paper mode tick delivery will be wired up in Milestone 8 when
        the paper trading engine is built.

        Raises:
            NotImplementedError: always, until implemented.
        """
        raise NotImplementedError(
            "PaperBroker.stream_ticks is not implemented yet. "
            "Live tick delivery for paper trading will be added in Milestone 8."
        )

    # ------------------------------------------------------------------
    # Order placement — BLOCKED (inherited from Broker base)
    # place_order, modify_order, cancel_order all raise LiveTradingDisabledError.
    # ------------------------------------------------------------------
