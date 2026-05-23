"""Gap Continuation strategy (backtest-only, v1).

Intraday momentum strategy for NSE cash equities:
  1. Detect opening gap (opening price vs previous day's closing price).
  2. If abs(gap_bps) is within [min_gap_bps, max_gap_bps], qualify the gap.
  3. After entry_start_time, enter in the GAP DIRECTION when price confirms
     continuation_trigger_bps from the opening price.
     Gap-up  -> enter LONG  (price continues up).
     Gap-down -> enter SHORT (price continues down).
  4. Exit on stop-loss, fixed target (target_bps), or square-off at 15:15.

No live order placement. No broker API calls. Backtest use only.

Prior close tracking
---------------------
The strategy carries the previous day's closing price across session
boundaries.  The first trading day in any dataset is always skipped because
no prior close is available.

Gap detection
-------------
  gap_bps = (opening_price / prior_close - 1) * 10000
  Gap-up   (gap_bps > 0) -> enter LONG  if allow_long_continuations=True.
  Gap-down (gap_bps < 0) -> enter SHORT if allow_short_continuations=True.

Entry trigger
--------------
  Gap-up  long:  bar.close >= opening_price * (1 + continuation_trigger_bps/10000)
  Gap-down short: bar.close <= opening_price * (1 - continuation_trigger_bps/10000)

Exit
-----
  stop_loss_bps: fixed stop from entry price.
  target_bps:    fixed profit target from entry price (None = square-off only).
  square_off_time: forced exit at this time.

Exit reasons
-------------
  "gc_stop_loss"   -- stop-loss hit
  "gc_target"      -- fixed target reached
  "gc_square_off"  -- bar timestamp >= square_off_time
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal

from trading_engine.strategy.base import Strategy, StrategyContext
from trading_engine.strategy.signals import Bar, OrderIntent

_TEN_THOUSAND = Decimal("10000")
_ZERO = Decimal("0")
_ONE = Decimal("1")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class GapContinuationConfig:
    """Configuration for GapContinuationStrategy."""

    strategy_id: str = "gap_cont_v1"
    exchange: str = "NSE"
    product: str = "MIS"
    quantity: int = 10
    session_start: time = field(default_factory=lambda: time(9, 15))
    entry_start_time: time = field(default_factory=lambda: time(9, 20))
    latest_entry_time: time = field(default_factory=lambda: time(10, 30))
    square_off_time: time = field(default_factory=lambda: time(15, 15))
    min_gap_bps: float = 60.0
    max_gap_bps: float = 300.0
    continuation_trigger_bps: float = 20.0
    stop_loss_bps: float = 80.0
    target_bps: float | None = None
    max_trades_per_symbol_per_day: int = 1
    allow_long_continuations: bool = True
    allow_short_continuations: bool = True
    min_opening_volume: int | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")
        if self.min_gap_bps <= 0:
            raise ValueError(f"min_gap_bps must be positive, got {self.min_gap_bps}")
        if self.max_gap_bps <= self.min_gap_bps:
            raise ValueError(
                f"max_gap_bps ({self.max_gap_bps}) must exceed min_gap_bps ({self.min_gap_bps})"
            )
        if self.continuation_trigger_bps <= 0:
            raise ValueError(
                f"continuation_trigger_bps must be positive, got {self.continuation_trigger_bps}"
            )
        if self.stop_loss_bps <= 0:
            raise ValueError(f"stop_loss_bps must be positive, got {self.stop_loss_bps}")
        if self.target_bps is not None and self.target_bps <= 0:
            raise ValueError(f"target_bps must be positive when set, got {self.target_bps}")
        if self.max_trades_per_symbol_per_day < 1:
            raise ValueError(
                f"max_trades_per_symbol_per_day must be >= 1, "
                f"got {self.max_trades_per_symbol_per_day}"
            )
        if self.square_off_time <= self.latest_entry_time:
            raise ValueError(
                f"square_off_time ({self.square_off_time}) must be after "
                f"latest_entry_time ({self.latest_entry_time})"
            )


# ---------------------------------------------------------------------------
# Per-symbol daily state
# ---------------------------------------------------------------------------


@dataclass
class _SymbolState:
    """Mutable per-symbol state for GapContinuationStrategy."""

    current_date: date | None = None

    # Inter-day carry -- NOT reset on new day
    prior_close: Decimal | None = None
    last_close: Decimal | None = None

    # Intraday gap analysis
    opening_bar_seen: bool = False
    opening_price: Decimal | None = None
    opening_volume: int = 0
    gap_bps: Decimal | None = None
    gap_qualified: bool = False
    gap_direction: str = ""  # "LONG" or "SHORT"

    # Position tracking
    in_position: bool = False
    position_side: str = ""  # "LONG" or "SHORT"
    entry_price: Decimal | None = None
    stop_price: Decimal | None = None
    target_price: Decimal | None = None

    # Daily counters
    bars_seen_today: int = 0
    trades_taken_today: int = 0

    def reset(self, new_date: date) -> None:
        """Reset intraday state for a new trading day; carry prior close."""
        self.prior_close = self.last_close  # inter-day carry
        self.last_close = None
        self.current_date = new_date
        self.opening_bar_seen = False
        self.opening_price = None
        self.opening_volume = 0
        self.gap_bps = None
        self.gap_qualified = False
        self.gap_direction = ""
        self.in_position = False
        self.position_side = ""
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.bars_seen_today = 0
        self.trades_taken_today = 0


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class GapContinuationStrategy(Strategy):
    """Gap Continuation strategy (backtest v1)."""

    def __init__(
        self,
        config: GapContinuationConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        cfg = config or GapContinuationConfig()
        super().__init__(strategy_id=cfg.strategy_id)
        self._config = cfg
        self._logger = logger or logging.getLogger(__name__)
        self._states: dict[str, _SymbolState] = {}

    def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
        """Process one bar; return zero or more OrderIntents."""
        state = self._get_state(bar.symbol)
        bar_date = _bar_date(bar)
        bar_time = _bar_time(bar)

        if state.current_date != bar_date:
            state.reset(bar_date)

        state.last_close = bar.close
        state.bars_seen_today += 1

        if not state.opening_bar_seen and bar_time >= self._config.session_start:
            self._process_opening_bar(bar, state)

        intents: list[OrderIntent] = []

        if state.in_position:
            exit_intent = self._check_exit(bar, bar_time, state)
            if exit_intent is not None:
                intents.append(exit_intent)
                state.in_position = False
                state.position_side = ""
                return intents

        if self._can_enter(bar_time, state):
            entry_intent = self._check_entry(bar, state)
            if entry_intent is not None:
                intents.append(entry_intent)
                self._set_position_state(bar, state)

        return intents

    def _process_opening_bar(self, bar: Bar, state: _SymbolState) -> None:
        state.opening_bar_seen = True
        state.opening_price = bar.open
        state.opening_volume = bar.volume

        if state.prior_close is None or state.prior_close == _ZERO:
            return

        gap = (state.opening_price / state.prior_close - _ONE) * _TEN_THOUSAND
        state.gap_bps = gap

        cfg = self._config
        abs_gap = abs(gap)
        min_gap = Decimal(str(cfg.min_gap_bps))
        max_gap = Decimal(str(cfg.max_gap_bps))

        if abs_gap < min_gap or abs_gap > max_gap:
            return

        if cfg.min_opening_volume is not None and state.opening_volume < cfg.min_opening_volume:
            return

        if gap > _ZERO and cfg.allow_long_continuations:
            state.gap_qualified = True
            state.gap_direction = "LONG"
        elif gap < _ZERO and cfg.allow_short_continuations:
            state.gap_qualified = True
            state.gap_direction = "SHORT"

    def _can_enter(self, bar_time: time, state: _SymbolState) -> bool:
        cfg = self._config
        return (
            state.gap_qualified
            and not state.in_position
            and state.trades_taken_today < cfg.max_trades_per_symbol_per_day
            and bar_time >= cfg.entry_start_time
            and bar_time <= cfg.latest_entry_time
            and state.opening_price is not None
        )

    def _check_entry(self, bar: Bar, state: _SymbolState) -> OrderIntent | None:
        cfg = self._config
        opening = state.opening_price
        assert opening is not None
        trigger_factor = Decimal(str(cfg.continuation_trigger_bps)) / _TEN_THOUSAND

        if state.gap_direction == "LONG":
            trigger_price = opening * (_ONE + trigger_factor)
            if bar.close < trigger_price:
                return None
            return OrderIntent(
                strategy_id=self.strategy_id,
                symbol=bar.symbol,
                exchange=bar.exchange,
                side="BUY",
                quantity=cfg.quantity,
                order_type="MARKET",
                product=cfg.product,
                reason="gc_long_entry",
            )

        if state.gap_direction == "SHORT":
            trigger_price = opening * (_ONE - trigger_factor)
            if bar.close > trigger_price:
                return None
            return OrderIntent(
                strategy_id=self.strategy_id,
                symbol=bar.symbol,
                exchange=bar.exchange,
                side="SELL",
                quantity=cfg.quantity,
                order_type="MARKET",
                product=cfg.product,
                reason="gc_short_entry",
            )

        return None

    def _set_position_state(self, bar: Bar, state: _SymbolState) -> None:
        entry_price = bar.close
        cfg = self._config
        sl_factor = Decimal(str(cfg.stop_loss_bps)) / _TEN_THOUSAND

        state.in_position = True
        state.position_side = state.gap_direction
        state.entry_price = entry_price
        state.trades_taken_today += 1

        if state.position_side == "LONG":
            state.stop_price = entry_price * (_ONE - sl_factor)
            if cfg.target_bps is not None:
                state.target_price = entry_price * (_ONE + Decimal(str(cfg.target_bps)) / _TEN_THOUSAND)
        else:
            state.stop_price = entry_price * (_ONE + sl_factor)
            if cfg.target_bps is not None:
                state.target_price = entry_price * (_ONE - Decimal(str(cfg.target_bps)) / _TEN_THOUSAND)

    def _check_exit(self, bar: Bar, bar_time: time, state: _SymbolState) -> OrderIntent | None:
        assert state.stop_price is not None

        if state.position_side == "LONG":
            stop_hit = bar.low <= state.stop_price
            target_hit = (
                state.target_price is not None and bar.high >= state.target_price
            )
        else:
            stop_hit = bar.high >= state.stop_price
            target_hit = (
                state.target_price is not None and bar.low <= state.target_price
            )

        square_off_hit = bar_time >= self._config.square_off_time

        if stop_hit:
            return self._exit_intent(bar, state, "gc_stop_loss")
        if target_hit:
            return self._exit_intent(bar, state, "gc_target")
        if square_off_hit:
            return self._exit_intent(bar, state, "gc_square_off")
        return None

    def _exit_intent(self, bar: Bar, state: _SymbolState, reason: str) -> OrderIntent:
        side = "SELL" if state.position_side == "LONG" else "BUY"
        return OrderIntent(
            strategy_id=self.strategy_id,
            symbol=bar.symbol,
            exchange=bar.exchange,
            side=side,
            quantity=self._config.quantity,
            order_type="MARKET",
            product=self._config.product,
            reason=reason,
        )

    def _get_state(self, symbol: str) -> _SymbolState:
        if symbol not in self._states:
            self._states[symbol] = _SymbolState()
        return self._states[symbol]


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def _bar_time(bar: Bar) -> time:
    ts = bar.timestamp
    if ts.tzinfo is not None:
        from zoneinfo import ZoneInfo
        ts = ts.astimezone(ZoneInfo("Asia/Kolkata"))
    return ts.time()


def _bar_date(bar: Bar) -> date:
    ts = bar.timestamp
    if ts.tzinfo is not None:
        from zoneinfo import ZoneInfo
        ts = ts.astimezone(ZoneInfo("Asia/Kolkata"))
    return ts.date()
