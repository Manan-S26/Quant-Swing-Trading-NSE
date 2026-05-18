"""Live execution safety guard.

LiveExecutionSafetyGuard is the final gatekeeper before any real order
placement path.  In this milestone, assert_order_placement_blocked_for_now()
always raises SafetyError — live order placement is not implemented.

assert_live_execution_allowed() checks the prerequisite conditions that would
be required before live execution could ever be enabled (LIVE_TRADING_ENABLED
flag, kill switch, etc.).  It is provided for documentation and future use,
but order placement still requires assert_order_placement_blocked_for_now()
to be removed in a future milestone.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from trading_engine.common.exceptions import SafetyError

if TYPE_CHECKING:
    from trading_engine.risk.kill_switch import KillSwitch


class LiveExecutionSafetyGuard:
    """Hard safety checks for the live execution path.

    Args:
        settings:    Settings object with a ``live_trading_enabled`` attribute.
        kill_switch: Optional KillSwitch instance.
        logger:      Optional logger override.

    In this milestone:
        - assert_order_placement_blocked_for_now() ALWAYS raises SafetyError.
          No real orders can pass through this guard.
        - assert_live_execution_allowed() validates prerequisites but does NOT
          remove the order-placement block.
    """

    def __init__(
        self,
        settings: Any,
        kill_switch: KillSwitch | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._settings = settings
        self._kill_switch = kill_switch
        self._log = logger or logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Primary safety gate — always blocks in this milestone
    # ------------------------------------------------------------------

    def assert_order_placement_blocked_for_now(self) -> None:
        """Raise SafetyError unconditionally.

        Real order placement is NOT implemented in Milestone 15.  Any code
        path that would place a real order must call this method first, so
        that attempting to reach the broker raises an explicit error rather
        than silently doing nothing.

        This method will be removed (or replaced with a real gate) in the
        milestone that implements live order execution.

        Raises:
            SafetyError: always.
        """
        raise SafetyError(
            "Live order placement is not implemented in this milestone. "
            "ZerodhaBroker.place_order() must not be called. "
            "Use paper trading (AUTO_PAPER) or dry-run mode to simulate orders."
        )

    # ------------------------------------------------------------------
    # Prerequisite checker for future live execution
    # ------------------------------------------------------------------

    def assert_live_execution_allowed(self) -> None:
        """Check that prerequisites for live execution are satisfied.

        This does NOT unblock order placement — that requires removing
        assert_order_placement_blocked_for_now().  This method exists to
        document and enforce the prerequisites that must all be true before
        live trading can even be considered.

        Raises:
            SafetyError: if LIVE_TRADING_ENABLED is False.
            SafetyError: if the kill switch is active.
        """
        live_enabled = getattr(self._settings, "live_trading_enabled", False)
        if not live_enabled:
            raise SafetyError(
                "LIVE_TRADING_ENABLED is False. "
                "Set LIVE_TRADING_ENABLED=true in your environment to enable live trading. "
                "Ensure you understand the risks before doing so."
            )

        if self._kill_switch is not None and self._kill_switch.is_active():
            raise SafetyError(
                f"Kill switch is active — reason: {self._kill_switch.reason!r}. "
                "Deactivate the kill switch before attempting live execution."
            )

        self._log.info("LiveExecutionSafetyGuard: prerequisites satisfied.")
