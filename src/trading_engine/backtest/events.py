"""Backtest event types.

Simple dataclass events passed through the backtest engine loop.
No event bus — the engine iterates events directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trading_engine.domain.models import TradeFill
from trading_engine.strategy.signals import Bar, OrderIntent


@dataclass(frozen=True)
class BacktestEvent:
    """Base class for all backtest events."""

    timestamp: datetime


@dataclass(frozen=True)
class MarketDataEvent(BacktestEvent):
    """A new bar is available for a symbol."""

    symbol: str
    bar: Bar


@dataclass(frozen=True)
class SignalEvent(BacktestEvent):
    """A strategy has emitted an order intent."""

    strategy_id: str
    order_intent: OrderIntent


@dataclass(frozen=True)
class OrderEvent(BacktestEvent):
    """An order has been submitted to the simulated broker."""

    symbol: str
    side: str
    quantity: int
    order_type: str
    price: object = None  # Decimal | None


@dataclass(frozen=True)
class FillEvent(BacktestEvent):
    """An order has been filled."""

    trade_fill: TradeFill


@dataclass(frozen=True)
class BacktestCompleteEvent(BacktestEvent):
    """The backtest run has finished."""

    reason: str
