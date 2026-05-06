"""Kill switch for the trading engine.

When active, the risk engine rejects all new orders regardless of other limits.
"""

from __future__ import annotations

from datetime import datetime


class KillSwitch:
    """Global emergency stop that blocks all new orders when active.

    Thread-safety: not thread-safe in v1.  Backtest runs are single-threaded.

    Example::

        ks = KillSwitch()
        ks.activate("daily loss limit hit")
        assert ks.is_active()
        ks.deactivate()
        assert not ks.is_active()
    """

    def __init__(self) -> None:
        self._active: bool = False
        self._reason: str | None = None
        self._activated_at: datetime | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def activate(self, reason: str) -> None:
        """Activate the kill switch.

        Args:
            reason: Non-empty string explaining why the switch was activated.

        Raises:
            ValueError: If reason is empty or whitespace-only.
        """
        if not reason.strip():
            raise ValueError("Kill switch activation reason cannot be empty.")
        self._active = True
        self._reason = reason
        self._activated_at = datetime.utcnow()

    def deactivate(self) -> None:
        """Deactivate the kill switch (reset to inactive state)."""
        self._active = False
        self._reason = None
        self._activated_at = None

    def is_active(self) -> bool:
        """Return True if the kill switch is currently active."""
        return self._active

    @property
    def reason(self) -> str | None:
        """The reason the kill switch was activated, or None if inactive."""
        return self._reason

    @property
    def activated_at(self) -> datetime | None:
        """The time the kill switch was activated, or None if inactive."""
        return self._activated_at
