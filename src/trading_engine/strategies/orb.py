"""Opening Range Breakout (ORB) strategy.

Classic intraday strategy for NSE cash equities:
  1. Record the high and low of the first N minutes after market open (the
     "opening range").
  2. After the opening range closes, enter LONG if price breaks above the
     opening range high.
  3. Exit on stop-loss, profit target, or square-off time.

Version 1 is long-only.  Short-side breakdowns are ignored.

State management
----------------
Per-symbol state is reset at the start of each new trading day so that the
strategy works correctly in multi-day backtests.

Fill price assumption
---------------------
The BacktestEngine does not currently send fill confirmations back to
strategies.  After emitting an entry OrderIntent the strategy optimistically
assumes the MARKET order filled at the current bar's close price, which is
consistent with SimulatedBroker's behaviour.  Stop and target prices are
computed from that assumed fill price.

Supported exit reasons
----------------------
  "orb_stop_loss"   — bar.low touched or crossed stop_price
  "orb_target"      — bar.high touched or crossed target_price
  "orb_square_off"  — bar timestamp is at or after square_off_time

If stop and target are both touched in the same bar the stop-loss is
preferred (conservative worst-case assumption).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from trading_engine.strategy.base import Strategy, StrategyContext
from trading_engine.strategy.signals import Bar, OrderIntent

_MARKET_OPEN: time = time(9, 15)
_TEN_THOUSAND = Decimal("10000")
_ZERO = Decimal("0")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class ORBConfig:
    """Configuration for the OpeningRangeBreakoutStrategy.

    Args:
        strategy_id:            Identifier for the strategy run.
        opening_range_minutes:  Number of minutes after market open that
                                define the opening range.  Positive integer.
        quantity:               Number of shares to trade per signal.
        target_r_multiple:      Target as a multiple of initial risk.
                                E.g. 2.0 → target = entry + 2 × risk.
        stop_buffer_bps:        Additional basis points subtracted from
                                opening_range_low to set the stop price.
                                0 means stop = opening_range_low exactly.
        entry_buffer_bps:       Additional basis points added to
                                opening_range_high to define the breakout
                                trigger level.  0 means trigger = OR high.
        square_off_time:        Time at or after which any open position is
                                closed regardless of P&L.  Defaults to 15:15.
        allow_reentry:          If True, allows a new entry on the same day
                                after an exit.  Defaults to False.
        long_only:              Must be True for v1.  Setting False raises
                                NotImplementedError.
    """

    strategy_id: str = "orb_v1"
    opening_range_minutes: int = 15
    quantity: int = 1
    target_r_multiple: Decimal = field(default_factory=lambda: Decimal("2.0"))
    stop_buffer_bps: Decimal = field(default_factory=lambda: Decimal("0"))
    entry_buffer_bps: Decimal = field(default_factory=lambda: Decimal("0"))
    square_off_time: time = field(default_factory=lambda: time(15, 15))
    allow_reentry: bool = False
    long_only: bool = True

    def __post_init__(self) -> None:
        if self.opening_range_minutes <= 0:
            raise ValueError(
                f"opening_range_minutes must be positive, got {self.opening_range_minutes}"
            )
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")
        if self.target_r_multiple <= _ZERO:
            raise ValueError(f"target_r_multiple must be positive, got {self.target_r_multiple}")
        if self.stop_buffer_bps < _ZERO:
            raise ValueError(f"stop_buffer_bps cannot be negative, got {self.stop_buffer_bps}")
        if self.entry_buffer_bps < _ZERO:
            raise ValueError(f"entry_buffer_bps cannot be negative, got {self.entry_buffer_bps}")
        if not self.long_only:
            raise NotImplementedError(
                "Short selling is not supported in ORB v1.  Set long_only=True."
            )


# ---------------------------------------------------------------------------
# Per-symbol state
# ---------------------------------------------------------------------------


@dataclass
class _SymbolState:
    """Mutable state tracked per symbol, per trading day."""

    current_date: date | None = None
    opening_range_high: Decimal | None = None
    opening_range_low: Decimal | None = None
    opening_range_complete: bool = False
    entered_today: bool = False
    in_position: bool = False
    entry_price: Decimal | None = None
    stop_price: Decimal | None = None
    target_price: Decimal | None = None
    exited_today: bool = False

    def reset(self, new_date: date) -> None:
        """Reset all intraday state for a new trading day."""
        self.current_date = new_date
        self.opening_range_high = None
        self.opening_range_low = None
        self.opening_range_complete = False
        self.entered_today = False
        self.in_position = False
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.exited_today = False


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class OpeningRangeBreakoutStrategy(Strategy):
    """Opening Range Breakout strategy (long-only, backtest v1).

    Construct with an ORBConfig to customise the opening range window,
    risk/reward ratio, buffers, and square-off time.

    Example::

        config = ORBConfig(opening_range_minutes=15, quantity=10,
                           target_r_multiple=Decimal("2"))
        strategy = OpeningRangeBreakoutStrategy(config=config)

    The strategy is designed to be stateless between days: on the first bar
    of each new date it resets its per-symbol tracking state automatically.
    """

    def __init__(
        self,
        config: ORBConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        cfg = config or ORBConfig()
        super().__init__(strategy_id=cfg.strategy_id)
        self._config = cfg
        self._logger = logger or logging.getLogger(__name__)
        self._states: dict[str, _SymbolState] = {}
        # Compute opening range end time once.
        range_end_dt = datetime.combine(date(2000, 1, 1), _MARKET_OPEN) + timedelta(
            minutes=self._config.opening_range_minutes
        )
        self._range_end: time = range_end_dt.time()

    # ------------------------------------------------------------------
    # Strategy interface
    # ------------------------------------------------------------------

    def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
        """Process a single bar and return zero or more OrderIntents."""
        state = self._get_state(bar.symbol)
        bar_date = _bar_date(bar)
        bar_time = _bar_time(bar)

        # Reset state at the start of each new trading day.
        if state.current_date != bar_date:
            state.reset(bar_date)

        intents: list[OrderIntent] = []

        # ── Opening range accumulation ──────────────────────────────────
        if not state.opening_range_complete:
            if bar_time < self._range_end:
                # Still inside the opening range window — update high/low.
                if state.opening_range_high is None or bar.high > state.opening_range_high:
                    state.opening_range_high = bar.high
                if state.opening_range_low is None or bar.low < state.opening_range_low:
                    state.opening_range_low = bar.low
                return intents
            else:
                # First bar after the opening range — mark complete and fall
                # through to exit/entry checks on this same bar.
                state.opening_range_complete = True

        # ── Exit checks (evaluated before new entries) ──────────────────
        if state.in_position:
            exit_intent = self._check_exit(bar, bar_time, state)
            if exit_intent is not None:
                intents.append(exit_intent)
                state.in_position = False
                state.exited_today = True
                # When allow_reentry is False, keep entered_today=True so
                # no further entry is attempted on the same day.
                # When allow_reentry is True, reset entered_today so the
                # strategy can enter again on a new signal.
                if self._config.allow_reentry:
                    state.entered_today = False
                return intents

        # ── Entry check ─────────────────────────────────────────────────
        if not state.entered_today and not state.in_position:
            entry_intent = self._check_entry(bar, state)
            if entry_intent is not None:
                intents.append(entry_intent)
                # Optimistically assume MARKET fill at bar close.
                entry_price = bar.close
                stop_price = self._stop_price(state)
                risk = entry_price - stop_price
                if risk > _ZERO:
                    state.in_position = True
                    state.entered_today = True
                    state.entry_price = entry_price
                    state.stop_price = stop_price
                    state.target_price = entry_price + self._config.target_r_multiple * risk
                else:
                    # Risk is zero or negative — cancel the intent.
                    self._logger.warning(
                        "%s: risk per share ≤ 0 after entry at %s (stop %s); ignoring entry.",
                        bar.symbol,
                        entry_price,
                        stop_price,
                    )
                    intents.clear()

        return intents

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_state(self, symbol: str) -> _SymbolState:
        if symbol not in self._states:
            self._states[symbol] = _SymbolState()
        return self._states[symbol]

    def _stop_price(self, state: _SymbolState) -> Decimal:
        """Opening range low minus optional stop buffer."""
        assert state.opening_range_low is not None
        low = state.opening_range_low
        buffer = low * self._config.stop_buffer_bps / _TEN_THOUSAND
        return low - buffer

    def _entry_trigger(self, state: _SymbolState) -> Decimal:
        """Opening range high plus optional entry buffer."""
        assert state.opening_range_high is not None
        high = state.opening_range_high
        buffer = high * self._config.entry_buffer_bps / _TEN_THOUSAND
        return high + buffer

    def _check_entry(self, bar: Bar, state: _SymbolState) -> OrderIntent | None:
        """Return a BUY OrderIntent if a long breakout is detected."""
        if state.opening_range_high is None or state.opening_range_low is None:
            return None
        trigger = self._entry_trigger(state)
        if bar.high >= trigger:
            return OrderIntent(
                strategy_id=self.strategy_id,
                symbol=bar.symbol,
                exchange=bar.exchange,
                side="BUY",
                quantity=self._config.quantity,
                order_type="MARKET",
                product="MIS",
                reason="orb_breakout_long",
            )
        return None

    def _check_exit(self, bar: Bar, bar_time: time, state: _SymbolState) -> OrderIntent | None:
        """Return a SELL OrderIntent if an exit condition is met.

        Priority (if multiple are triggered on the same bar):
          1. Stop-loss  (conservative)
          2. Target
          3. Square-off
        """
        assert state.stop_price is not None
        assert state.target_price is not None

        # Square-off time — must exit regardless.
        if bar_time >= self._config.square_off_time:
            return self._sell_intent(bar, "orb_square_off")

        stop_hit = bar.low <= state.stop_price
        target_hit = bar.high >= state.target_price

        if stop_hit and target_hit:
            # Conservative: assume stop was filled first.
            return self._sell_intent(bar, "orb_stop_loss")
        if stop_hit:
            return self._sell_intent(bar, "orb_stop_loss")
        if target_hit:
            return self._sell_intent(bar, "orb_target")

        return None

    def _sell_intent(self, bar: Bar, reason: str) -> OrderIntent:
        return OrderIntent(
            strategy_id=self.strategy_id,
            symbol=bar.symbol,
            exchange=bar.exchange,
            side="SELL",
            quantity=self._config.quantity,
            order_type="MARKET",
            product="MIS",
            reason=reason,
        )


# ---------------------------------------------------------------------------
# Timestamp helpers (handle both timezone-aware and naive timestamps)
# ---------------------------------------------------------------------------


def _bar_time(bar: Bar) -> time:
    """Return the bar's time component, converting to IST if timezone-aware."""
    ts = bar.timestamp
    if ts.tzinfo is not None:
        from zoneinfo import ZoneInfo

        ts = ts.astimezone(ZoneInfo("Asia/Kolkata"))
    return ts.time()


def _bar_date(bar: Bar) -> date:
    """Return the bar's date, converting to IST if timezone-aware."""
    ts = bar.timestamp
    if ts.tzinfo is not None:
        from zoneinfo import ZoneInfo

        ts = ts.astimezone(ZoneInfo("Asia/Kolkata"))
    return ts.date()
