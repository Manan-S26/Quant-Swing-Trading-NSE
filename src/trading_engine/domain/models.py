"""Pydantic v2 domain models for the trading engine.

These models are the internal vocabulary shared by:
  - the risk engine (RiskDecision)
  - the order manager (InternalOrder)
  - the portfolio engine (TradeFill, Position, PortfolioSnapshot)
  - the Zerodha adapter (Instrument)

All models are broker-independent. No Zerodha SDK types appear here.
Live order placement is not implemented.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from trading_engine.domain.enums import (
    Exchange,
    OrderStatus,
    OrderType,
    ProductType,
    RiskReasonCode,
    Side,
    TimeInForce,
)


class Money(BaseModel):
    """A monetary amount with currency."""

    amount: Decimal
    currency: str = "INR"

    @field_validator("currency")
    @classmethod
    def currency_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("currency cannot be empty")
        return v


class Instrument(BaseModel):
    """A tradable instrument (stock, ETF, etc.)."""

    symbol: str
    exchange: Exchange
    instrument_token: int | None = None
    name: str | None = None
    tick_size: Decimal | None = None
    lot_size: int = 1
    is_active: bool = True

    @field_validator("symbol")
    @classmethod
    def symbol_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("symbol cannot be empty")
        return v

    @field_validator("lot_size")
    @classmethod
    def lot_size_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"lot_size must be positive, got {v}")
        return v

    @field_validator("tick_size")
    @classmethod
    def tick_size_positive(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError(f"tick_size must be positive if provided, got {v}")
        return v


class RiskDecision(BaseModel):
    """The risk engine's verdict on an OrderIntent.

    Every order that reaches the order manager must have a RiskDecision
    attached. If approved is False, the order must not be submitted.
    """

    risk_decision_id: str
    approved: bool
    reason_code: RiskReasonCode
    reason_message: str
    checked_limits: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime

    @field_validator("reason_message")
    @classmethod
    def reason_message_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("reason_message cannot be empty")
        return v

    @model_validator(mode="after")
    def validate_approval_consistency(self) -> RiskDecision:
        """A rejected decision must not carry the APPROVED reason code."""
        if not self.approved and self.reason_code == RiskReasonCode.APPROVED:
            raise ValueError(
                "approved=False is inconsistent with reason_code=APPROVED. "
                "Use a rejection reason code (e.g. LIVE_TRADING_DISABLED)."
            )
        return self


class InternalOrder(BaseModel):
    """An order tracked internally by the trading engine.

    This is distinct from any broker-side order representation.
    The broker_order_id is populated only after successful submission.
    """

    internal_order_id: str
    broker_order_id: str | None = None
    strategy_id: str
    symbol: str
    exchange: Exchange
    side: Side
    quantity: int
    order_type: OrderType
    product: ProductType
    price: Decimal | None = None
    trigger_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    status: OrderStatus = OrderStatus.CREATED
    risk_decision_id: str | None = None
    created_at: datetime
    updated_at: datetime
    raw_broker_response: dict[str, Any] | None = None

    @field_validator("strategy_id", "symbol")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field cannot be empty")
        return v

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"quantity must be positive, got {v}")
        return v

    @field_validator("price")
    @classmethod
    def price_positive(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError(f"price must be positive if provided, got {v}")
        return v

    @field_validator("trigger_price")
    @classmethod
    def trigger_price_positive(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError(f"trigger_price must be positive if provided, got {v}")
        return v

    @model_validator(mode="after")
    def validate_order_constraints(self) -> InternalOrder:
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("LIMIT orders require a price.")
        if self.order_type in (OrderType.SL, OrderType.SL_M) and self.trigger_price is None:
            raise ValueError(f"{self.order_type} orders require a trigger_price.")
        if self.updated_at < self.created_at:
            raise ValueError(
                f"updated_at ({self.updated_at}) cannot be before created_at ({self.created_at})."
            )
        return self


class TradeFill(BaseModel):
    """A single executed fill (partial or full) for an internal order."""

    fill_id: str
    internal_order_id: str
    broker_order_id: str | None = None
    symbol: str
    exchange: Exchange
    side: Side
    quantity: int
    price: Decimal
    fees: Decimal = Decimal("0")
    timestamp: datetime

    @field_validator("internal_order_id", "symbol")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field cannot be empty")
        return v

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"quantity must be positive, got {v}")
        return v

    @field_validator("price")
    @classmethod
    def price_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError(f"price must be positive, got {v}")
        return v

    @field_validator("fees")
    @classmethod
    def fees_not_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError(f"fees cannot be negative, got {v}")
        return v


class Position(BaseModel):
    """Current open position in a symbol."""

    symbol: str
    exchange: Exchange
    product: ProductType
    quantity: int
    average_price: Decimal
    last_price: Decimal | None = None
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    updated_at: datetime

    @field_validator("symbol")
    @classmethod
    def symbol_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("symbol cannot be empty")
        return v

    @field_validator("average_price")
    @classmethod
    def average_price_not_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError(f"average_price cannot be negative, got {v}")
        return v

    @field_validator("last_price")
    @classmethod
    def last_price_not_negative(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v < 0:
            raise ValueError(f"last_price cannot be negative if provided, got {v}")
        return v


class PortfolioSnapshot(BaseModel):
    """Point-in-time snapshot of the portfolio for risk and reporting."""

    timestamp: datetime
    cash: Decimal
    positions: list[Position]
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal

    @field_validator("gross_exposure")
    @classmethod
    def gross_exposure_not_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError(f"gross_exposure cannot be negative, got {v}")
        return v
