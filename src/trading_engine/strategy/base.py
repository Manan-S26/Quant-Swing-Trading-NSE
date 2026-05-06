"""Strategy base class.

All trading strategies must subclass Strategy and implement on_bar().

Key design rules:
  - Strategies must not import or call broker-specific modules.
  - Strategies must not place orders directly.
  - on_bar() and on_tick() return lists of OrderIntent objects.
  - The risk engine and order manager handle everything after that.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from trading_engine.strategy.signals import Bar, OrderIntent, Tick

logger = logging.getLogger(__name__)


class StrategyContext:
    """Read-only context injected into every strategy callback.

    Provides the strategy with:
      - its own ID and mode
      - config values
      - a logger scoped to the strategy

    Strategies must not store a reference to StrategyContext beyond a single
    callback invocation — its contents may change between calls.
    """

    def __init__(
        self,
        strategy_id: str,
        mode: str,
        config: dict[str, Any],
    ) -> None:
        if mode not in ("backtest", "paper", "live"):
            raise ValueError(f"Unknown mode: {mode!r}. Expected backtest, paper, or live.")
        self.strategy_id = strategy_id
        self.mode = mode
        self.config: dict[str, Any] = config
        self.logger: logging.Logger = logging.getLogger(
            f"strategy.{strategy_id}"
        )

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    @property
    def is_paper(self) -> bool:
        return self.mode == "paper"

    @property
    def is_backtest(self) -> bool:
        return self.mode == "backtest"


class Strategy(ABC):
    """Abstract base class for all intraday stock trading strategies.

    Subclass this and implement at minimum on_bar(). Return zero or more
    OrderIntent objects from on_bar() or on_tick(). Do not call the broker.

    Example:
        class MyStrategy(Strategy):
            def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
                return []
    """

    def __init__(self, strategy_id: str, config: dict[str, Any] | None = None) -> None:
        self.strategy_id = strategy_id
        self.config: dict[str, Any] = config or {}
        self._logger = logging.getLogger(f"strategy.{strategy_id}")

    def on_start(self, context: StrategyContext) -> None:
        """Called once when the strategy runner initialises the strategy."""

    @abstractmethod
    def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
        """Called for each completed bar. Return zero or more OrderIntents."""

    def on_tick(self, tick: Tick, context: StrategyContext) -> list[OrderIntent]:
        """Called for each live tick. Return zero or more OrderIntents.

        Default implementation does nothing. Override for tick-level logic.
        """
        return []

    def on_order_update(
        self, order_update: dict[str, Any], context: StrategyContext
    ) -> None:
        """Called when an order's status changes.

        Use this to track fills, cancellations, or rejections if the strategy
        needs to react (e.g. place a paired exit order).
        """

    def on_stop(self, context: StrategyContext) -> None:
        """Called once when the strategy runner is stopping."""
