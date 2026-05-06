"""Risk limit configuration.

RiskLimits is a plain dataclass so it can be constructed without Pydantic
overhead in hot paths. Validation is done in __post_init__.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from trading_engine.domain.enums import OrderType, ProductType

_ZERO = Decimal("0")


@dataclass
class RiskLimits:
    """Pre-trade risk limits applied to every OrderIntent.

    Args:
        max_daily_loss:         Maximum cumulative realized + unrealized loss
                                for the day (positive number; e.g. Decimal("2000")).
        max_order_value:        Maximum notional value per single order (INR).
        max_open_positions:     Maximum number of symbols with a non-zero
                                long position at any one time.
        max_trades_per_day:     Maximum total fill count for the day.
        max_orders_per_second:  Maximum new orders submitted per second.
                                Enforced by counting within a 1-second window.
        allowed_symbols:        If not None, only these symbols are permitted.
        allowed_product_types:  If not None, only these product types allowed.
        allowed_order_types:    If not None, only these order types allowed.
    """

    max_daily_loss: Decimal = field(default_factory=lambda: Decimal("10000"))
    max_order_value: Decimal = field(default_factory=lambda: Decimal("500000"))
    max_open_positions: int = 10
    max_trades_per_day: int = 100
    max_orders_per_second: int = 5
    allowed_symbols: set[str] | None = None
    allowed_product_types: set[ProductType] | None = None
    allowed_order_types: set[OrderType] | None = None

    def __post_init__(self) -> None:
        if self.max_daily_loss <= _ZERO:
            raise ValueError(f"max_daily_loss must be positive, got {self.max_daily_loss}")
        if self.max_order_value <= _ZERO:
            raise ValueError(f"max_order_value must be positive, got {self.max_order_value}")
        if self.max_open_positions <= 0:
            raise ValueError(f"max_open_positions must be positive, got {self.max_open_positions}")
        if self.max_trades_per_day <= 0:
            raise ValueError(f"max_trades_per_day must be positive, got {self.max_trades_per_day}")
        if self.max_orders_per_second <= 0:
            raise ValueError(
                f"max_orders_per_second must be positive, got {self.max_orders_per_second}"
            )
