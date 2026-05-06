"""Paper trading event types.

Frozen dataclasses used to signal state changes within the paper trading engine.
No Zerodha imports. No real broker calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trading_engine.domain.models import RiskDecision, TradeFill
from trading_engine.strategy.signals import Bar, OrderIntent


@dataclass(frozen=True)
class PaperMarketDataEvent:
    """A new bar has arrived from the paper market feed."""

    symbol: str
    bar: Bar
    timestamp: datetime


@dataclass(frozen=True)
class PaperSignalEvent:
    """A strategy has emitted an OrderIntent."""

    strategy_id: str
    order_intent: OrderIntent
    timestamp: datetime


@dataclass(frozen=True)
class PaperFillEvent:
    """An order intent was executed and produced a fill."""

    trade_fill: TradeFill


@dataclass(frozen=True)
class PaperRiskRejectedEvent:
    """An order intent was rejected by the risk engine."""

    order_intent: OrderIntent
    decision: RiskDecision


@dataclass(frozen=True)
class PaperCompleteEvent:
    """The paper trading run has finished."""

    reason: str
