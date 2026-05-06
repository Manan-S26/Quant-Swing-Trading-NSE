"""Clock abstraction for the trading engine.

Using a Clock interface (rather than datetime.now() directly) allows strategies
and the backtester to share the same code while running in real-time or
simulated time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# NSE cash equity session boundaries
MARKET_OPEN: time = time(9, 15)
NO_NEW_ORDERS_AFTER: time = time(15, 0)
SQUARE_OFF_TIME: time = time(15, 15)
MARKET_CLOSE: time = time(15, 30)


class Clock(ABC):
    """Abstract clock interface."""

    @abstractmethod
    def now(self) -> datetime:
        """Return the current time (timezone-aware, UTC)."""

    def now_ist(self) -> datetime:
        """Return current time in IST."""
        return self.now().astimezone(IST)

    def is_market_open(self) -> bool:
        """Return True if NSE market session is active."""
        t = self.now_ist().time()
        return MARKET_OPEN <= t <= MARKET_CLOSE

    def can_place_new_order(self) -> bool:
        """Return True if new intraday orders are allowed (before 15:00 IST)."""
        t = self.now_ist().time()
        return MARKET_OPEN <= t < NO_NEW_ORDERS_AFTER

    def must_square_off(self) -> bool:
        """Return True if intraday positions must be squared off."""
        t = self.now_ist().time()
        return t >= SQUARE_OFF_TIME


class LiveClock(Clock):
    """Returns real wall-clock time."""

    def now(self) -> datetime:
        return datetime.now(tz=timezone.utc)


class SimulatedClock(Clock):
    """Deterministic clock for backtesting and unit tests."""

    def __init__(self, current_time: datetime) -> None:
        if current_time.tzinfo is None:
            raise ValueError("SimulatedClock requires a timezone-aware datetime.")
        self._time = current_time

    def now(self) -> datetime:
        return self._time

    def advance(self, **kwargs: int) -> None:
        """Advance the clock by the given timedelta kwargs (e.g. minutes=1)."""
        self._time += timedelta(**kwargs)

    def set(self, new_time: datetime) -> None:
        """Jump to a specific time."""
        if new_time.tzinfo is None:
            raise ValueError("SimulatedClock.set() requires a timezone-aware datetime.")
        self._time = new_time
