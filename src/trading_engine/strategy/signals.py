"""Core domain objects for strategy input and output.

Strategies receive Bar and Tick events and emit OrderIntent objects.
They must never import Zerodha-specific modules or place orders directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from trading_engine.common.exceptions import OrderValidationError

_VALID_SIDES = frozenset({"BUY", "SELL"})
_VALID_ORDER_TYPES = frozenset({"MARKET", "LIMIT", "SL", "SL-M"})
_VALID_PRODUCTS = frozenset({"MIS", "CNC", "NRML"})


@dataclass(frozen=True)
class Bar:
    """An OHLCV candle for a single symbol."""

    symbol: str
    exchange: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    interval: str = "1m"

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError(f"Bar high ({self.high}) cannot be less than low ({self.low})")
        if self.volume < 0:
            raise ValueError(f"Bar volume cannot be negative: {self.volume}")


@dataclass(frozen=True)
class Tick:
    """A single market tick (best bid/ask + last traded price)."""

    symbol: str
    exchange: str
    timestamp: datetime
    last_price: Decimal
    volume: int
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None

    def __post_init__(self) -> None:
        if self.last_price <= 0:
            raise ValueError(f"Tick last_price must be positive: {self.last_price}")


@dataclass
class OrderIntent:
    """What a strategy wants to do.

    Strategies emit OrderIntents. The risk engine decides whether each intent
    is allowed. The order manager decides how and when to execute it.
    Strategies must never place orders directly.
    """

    strategy_id: str
    symbol: str
    exchange: str
    side: str  # BUY | SELL
    quantity: int
    order_type: str  # MARKET | LIMIT | SL | SL-M
    product: str  # MIS | CNC | NRML
    validity: str = "DAY"
    price: Optional[Decimal] = None
    trigger_price: Optional[Decimal] = None
    reason: str = ""
    strategy_version: str = "1"
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise OrderValidationError(
                f"OrderIntent quantity must be positive, got {self.quantity}"
            )
        if self.side not in _VALID_SIDES:
            raise OrderValidationError(
                f"OrderIntent side must be one of {_VALID_SIDES}, got {self.side!r}"
            )
        if self.order_type not in _VALID_ORDER_TYPES:
            raise OrderValidationError(
                f"OrderIntent order_type must be one of {_VALID_ORDER_TYPES}, "
                f"got {self.order_type!r}"
            )
        if self.product not in _VALID_PRODUCTS:
            raise OrderValidationError(
                f"OrderIntent product must be one of {_VALID_PRODUCTS}, got {self.product!r}"
            )
        if self.order_type == "LIMIT" and self.price is None:
            raise OrderValidationError("LIMIT order requires a price.")
        if self.order_type in ("SL", "SL-M") and self.trigger_price is None:
            raise OrderValidationError(f"{self.order_type} order requires a trigger_price.")


@dataclass(frozen=True)
class Signal:
    """An intermediate signal that a strategy may use internally.

    Signals are optional — strategies can emit OrderIntents directly.
    Use Signal to represent intermediate analytical conclusions before
    deciding on order parameters.
    """

    strategy_id: str
    symbol: str
    signal_type: str
    strength: float  # normalised, e.g. -1.0 to +1.0
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
