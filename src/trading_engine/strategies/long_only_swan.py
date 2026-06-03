"""Long-Only Black Swan (Relative Value) strategy.

Trades mean reversion of a spread between two highly cointegrated assets 
on a daily timeframe. However, to avoid shorting constraints in the cash market,
it only buys the underperformer in cash (CNC) and holds until the mean reverts.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from trading_engine.strategy.base import Strategy, StrategyContext
from trading_engine.strategy.signals import Bar, OrderIntent


@dataclass
class LongOnlySwanConfig:
    """Configuration for LongOnlySwanStrategy."""
    strategy_id: str = "long_only_swan"
    symbol_a: str = "HDFCBANK"
    symbol_b: str = "HDFCLIFE"
    capital_per_leg: int = 100000
    window_size: int = 120
    entry_z_score: float = 3.5
    exit_z_score: float = 0.0
    stop_loss_z_score: float = 5.0
    max_hold_days: int = 30
    
    def __post_init__(self) -> None:
        if self.capital_per_leg <= 0:
            raise ValueError("Capital must be positive.")
        if self.window_size <= 1:
            raise ValueError("window_size must be > 1 to calculate standard deviation.")
        if self.entry_z_score <= self.exit_z_score:
            raise ValueError("entry_z_score must be strictly greater than exit_z_score.")
        if self.stop_loss_z_score <= self.entry_z_score:
            raise ValueError("stop_loss_z_score must be strictly greater than entry_z_score.")

@dataclass
class _PairState:
    """State tracked for the pair."""
    last_bar_a: Bar | None = None
    last_bar_b: Bar | None = None
    ratio_history: list[float] = field(default_factory=list)
    position: str | None = None  # None, "LONG_A", or "LONG_B"
    entry_time: datetime | None = None
    entry_qty: int = 0

class LongOnlySwanStrategy(Strategy):
    """Long-Only Black Swan Trading Strategy."""

    def __init__(
        self,
        config: LongOnlySwanConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        cfg = config or LongOnlySwanConfig()
        super().__init__(strategy_id=cfg.strategy_id)
        self._config = cfg
        self._logger = logger or logging.getLogger(__name__)
        self._state = _PairState()

    def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
        intents: list[OrderIntent] = []
        
        if bar.symbol not in (self._config.symbol_a, self._config.symbol_b):
            return intents

        if bar.symbol == self._config.symbol_a:
            self._state.last_bar_a = bar
        elif bar.symbol == self._config.symbol_b:
            self._state.last_bar_b = bar

        if self._state.last_bar_a is None or self._state.last_bar_b is None:
            return intents

        if self._state.last_bar_a.timestamp != self._state.last_bar_b.timestamp:
            return intents

        price_a = float(self._state.last_bar_a.close)
        price_b = float(self._state.last_bar_b.close)
        
        if price_b == 0:
            return intents
            
        current_ratio = price_a / price_b
        self._state.ratio_history.append(current_ratio)

        if len(self._state.ratio_history) > self._config.window_size:
            self._state.ratio_history.pop(0)

        if len(self._state.ratio_history) < self._config.window_size:
            return intents

        mean_ratio = statistics.mean(self._state.ratio_history)
        stdev_ratio = statistics.stdev(self._state.ratio_history)
        
        if stdev_ratio == 0:
            return intents
            
        z_score = (current_ratio - mean_ratio) / stdev_ratio
        
        days_held = 0
        if self._state.entry_time:
            days_held = (bar.timestamp - self._state.entry_time).days

        if self._state.position == "LONG_A":
            if z_score <= -self._config.stop_loss_z_score:
                intents.append(self._create_intent(self._config.symbol_a, "SELL", self._state.entry_qty, bar.exchange, "long_a_stop_loss"))
                self._clear_position()
            elif z_score >= -self._config.exit_z_score:
                intents.append(self._create_intent(self._config.symbol_a, "SELL", self._state.entry_qty, bar.exchange, "long_a_exit"))
                self._clear_position()
            elif days_held >= self._config.max_hold_days:
                intents.append(self._create_intent(self._config.symbol_a, "SELL", self._state.entry_qty, bar.exchange, "long_a_time_exit"))
                self._clear_position()
                
        elif self._state.position == "LONG_B":
            if z_score >= self._config.stop_loss_z_score:
                intents.append(self._create_intent(self._config.symbol_b, "SELL", self._state.entry_qty, bar.exchange, "long_b_stop_loss"))
                self._clear_position()
            elif z_score <= self._config.exit_z_score:
                intents.append(self._create_intent(self._config.symbol_b, "SELL", self._state.entry_qty, bar.exchange, "long_b_exit"))
                self._clear_position()
            elif days_held >= self._config.max_hold_days:
                intents.append(self._create_intent(self._config.symbol_b, "SELL", self._state.entry_qty, bar.exchange, "long_b_time_exit"))
                self._clear_position()
                
        elif self._state.position is None:
            if z_score <= -self._config.entry_z_score:
                qty = max(1, int(self._config.capital_per_leg / price_a))
                intents.append(self._create_intent(self._config.symbol_a, "BUY", qty, bar.exchange, "long_a_entry"))
                self._set_position("LONG_A", bar.timestamp, qty)
                
            elif z_score >= self._config.entry_z_score:
                qty = max(1, int(self._config.capital_per_leg / price_b))
                intents.append(self._create_intent(self._config.symbol_b, "BUY", qty, bar.exchange, "long_b_entry"))
                self._set_position("LONG_B", bar.timestamp, qty)

        return intents
        
    def _clear_position(self) -> None:
        self._state.position = None
        self._state.entry_time = None
        self._state.entry_qty = 0
        
    def _set_position(self, pos: str, dt: datetime, qty: int) -> None:
        self._state.position = pos
        self._state.entry_time = dt
        self._state.entry_qty = qty

    def _create_intent(self, symbol: str, side: str, quantity: int, exchange: str, reason: str) -> OrderIntent:
        return OrderIntent(
            strategy_id=self.strategy_id,
            symbol=symbol,
            exchange=exchange,
            side=side,
            quantity=quantity,
            order_type="MARKET",
            product="CNC",
            reason=reason,
        )
