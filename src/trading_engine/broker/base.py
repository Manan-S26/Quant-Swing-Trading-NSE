"""Abstract broker interface.

All broker adapters (Zerodha live, paper, simulated) must implement this
interface. This keeps strategy code and the order manager decoupled from
any specific broker SDK.

IMPORTANT: place_order is intentionally blocked in this milestone.
Live order placement will be enabled only in Milestone 9, after the order
state machine, idempotency, risk engine, and reconciliation are complete.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from trading_engine.common.exceptions import LiveTradingDisabledError


class Broker(ABC):
    """Abstract interface for all broker adapters."""

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the broker."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the broker connection cleanly."""

    # ------------------------------------------------------------------
    # Read-only account data
    # ------------------------------------------------------------------

    @abstractmethod
    def get_positions(self) -> list[dict[str, Any]]:
        """Return all current open positions."""

    @abstractmethod
    def get_orders(self) -> list[dict[str, Any]]:
        """Return all orders placed today."""

    @abstractmethod
    def get_trades(self) -> list[dict[str, Any]]:
        """Return all executed trades today."""

    @abstractmethod
    def get_margins(self) -> dict[str, Any]:
        """Return available margin and fund information."""

    # ------------------------------------------------------------------
    # Market data streaming
    # ------------------------------------------------------------------

    def stream_ticks(self, symbols: list[str], callback: Any) -> None:
        """Subscribe to live tick updates for the given symbols.

        Override in concrete broker implementations that support streaming.
        The callback signature should be: callback(tick: dict) -> None.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement stream_ticks. "
            "Override this method in your broker subclass."
        )

    # ------------------------------------------------------------------
    # Order placement — BLOCKED until Milestone 9
    # ------------------------------------------------------------------

    def place_order(self, *args: Any, **kwargs: Any) -> None:
        """Live order placement is disabled in Milestone 1.

        This method exists on the interface so that the order manager can
        call it without knowing the concrete broker type. It will raise
        LiveTradingDisabledError until Milestone 9 is implemented and
        LIVE_TRADING_ENABLED=true is explicitly configured.
        """
        raise LiveTradingDisabledError(
            "place_order is not available in this milestone. "
            "Live order placement requires: "
            "(1) Milestone 9 order manager implemented, "
            "(2) LIVE_TRADING_ENABLED=true set explicitly, "
            "(3) risk engine approval. "
            "Do NOT bypass this check."
        )

    def modify_order(self, *args: Any, **kwargs: Any) -> None:
        """Order modification is disabled until Milestone 9."""
        raise LiveTradingDisabledError(
            "modify_order is not available in this milestone. See place_order."
        )

    def cancel_order(self, *args: Any, **kwargs: Any) -> None:
        """Order cancellation is disabled until Milestone 9."""
        raise LiveTradingDisabledError(
            "cancel_order is not available in this milestone. See place_order."
        )
