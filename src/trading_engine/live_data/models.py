"""Live market data domain models.

LiveTick represents a single real-time price update received from a WebSocket
feed. It is the entry point into the live_data pipeline and is feed-agnostic:
CandleBuilder consumes LiveTick objects regardless of the upstream source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


@dataclass
class LiveTick:
    """A single real-time price update from a live market data feed.

    Fields:
        instrument_token: Broker-side numeric token for the instrument.
        symbol:           Human-readable ticker symbol (e.g. "RELIANCE").
        exchange:         Exchange enum value (e.g. Exchange.NSE).
        timestamp:        When this tick was observed.
        last_price:       Last traded price. Must be positive.
        volume:           Cumulative day volume at this tick (optional).
        average_price:    Volume-weighted average price at this tick (optional).
        raw:              Raw dict from the upstream broker feed (optional).

    Validation:
        - instrument_token must be positive (> 0).
        - last_price must be positive (> 0).
        - volume, if provided, must be non-negative (>= 0).
    """

    instrument_token: int
    symbol: str | None
    exchange: Any | None  # Exchange | None — avoid circular import at runtime
    timestamp: datetime
    last_price: Decimal
    volume: int | None = None
    average_price: Decimal | None = None
    raw: dict[str, Any] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.instrument_token <= 0:
            raise ValueError(
                f"LiveTick.instrument_token must be positive, got {self.instrument_token}"
            )
        if self.last_price <= Decimal("0"):
            raise ValueError(f"LiveTick.last_price must be positive, got {self.last_price}")
        if self.volume is not None and self.volume < 0:
            raise ValueError(f"LiveTick.volume must be non-negative, got {self.volume}")
