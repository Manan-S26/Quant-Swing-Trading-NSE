"""VWAP Trend Pullback strategy (backtest-only, v1).

Intraday long-only strategy for NSE cash equities:
  1. Calculate intraday VWAP from minute bars (cumulative, reset each day).
  2. Only trade when VWAP slope over a lookback window is positive.
  3. Enter LONG when price pulls back toward VWAP and a confirmation bar closes
     above the prior bar's high (or above VWAP, depending on confirmation_mode).
  4. Exit on stop-loss, profit target, or square-off time.

No live order placement.  No broker API calls.  Backtest use only.

State management
----------------
Per-symbol state is fully reset at the start of each new trading day.

VWAP calculation
----------------
VWAP = Σ(typical_price_i × volume_i) / Σ(volume_i) where
typical_price = (high + low + close) / 3.
If volume is zero or missing on a bar, close is used as the price contribution
with an implicit weight of 1 to avoid divide-by-zero.

Fill price assumption
---------------------
After emitting a BUY OrderIntent the strategy optimistically assumes the
MARKET order fills at the bar's close, consistent with SimulatedBroker.

Exit reasons
------------
  "vwap_stop_loss"  — bar.low ≤ stop_price
  "vwap_target"     — bar.high ≥ target_price
  "vwap_square_off" — bar timestamp ≥ square_off_time
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
_THREE = Decimal("3")
_ONE = Decimal("1")

_VALID_CONFIRMATION_MODES = frozenset({"close_above_prior_high", "close_above_vwap"})


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class VWAPPullbackConfig:
    """Configuration for VWAPTrendPullbackStrategy.

    Args:
        strategy_id:                  Identifier for the strategy run.
        exchange:                     Exchange string, e.g. "NSE".
        product:                      Product type: "MIS" for intraday.
        quantity:                     Shares per signal. Positive integer.
        session_start:                Market session start time (09:15).
        no_trade_before:              No new entries before this time.
        no_new_entries_after:         No new entries at or after this time.
        square_off_time:              Force-close all positions at this time.
        vwap_slope_lookback_bars:     Number of VWAP values to compare for slope.
        min_bars_before_trading:      Minimum bars seen today before any entry.
                                      Must be >= vwap_slope_lookback_bars.
        pullback_tolerance_bps:       Bar's low must be ≤ VWAP × (1 + tol/10000).
                                      Allows the low to be slightly above VWAP.
        confirmation_mode:            "close_above_prior_high" — bar's close must
                                      exceed previous bar's high.
                                      "close_above_vwap" — bar's close must exceed
                                      current VWAP.
        stop_loss_bps:                Stop set this many bps below entry price.
        target_bps:                   Target set this many bps above entry price.
        max_trades_per_symbol_per_day: Maximum entries per symbol per day.
        allow_reentry:                If True, re-entry is allowed after exit
                                      (subject to max_trades_per_symbol_per_day).
        long_only:                    Must remain True; short side not implemented.
    """

    strategy_id: str = "vwap_pullback_v1"
    exchange: str = "NSE"
    product: str = "MIS"
    quantity: int = 10
    session_start: time = field(default_factory=lambda: time(9, 15))
    no_trade_before: time = field(default_factory=lambda: time(9, 30))
    no_new_entries_after: time = field(default_factory=lambda: time(14, 30))
    square_off_time: time = field(default_factory=lambda: time(15, 15))
    vwap_slope_lookback_bars: int = 5
    min_bars_before_trading: int = 15
    pullback_tolerance_bps: float = 20.0
    confirmation_mode: str = "close_above_prior_high"
    stop_loss_bps: float = 40.0
    target_bps: float = 80.0
    max_trades_per_symbol_per_day: int = 1
    allow_reentry: bool = False
    long_only: bool = True

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")
        if self.stop_loss_bps <= 0:
            raise ValueError(f"stop_loss_bps must be positive, got {self.stop_loss_bps}")
        if self.target_bps <= 0:
            raise ValueError(f"target_bps must be positive, got {self.target_bps}")
        if self.pullback_tolerance_bps < 0:
            raise ValueError(
                f"pullback_tolerance_bps cannot be negative, got {self.pullback_tolerance_bps}"
            )
        if self.vwap_slope_lookback_bars < 1:
            raise ValueError(
                f"vwap_slope_lookback_bars must be >= 1, got {self.vwap_slope_lookback_bars}"
            )
        if self.min_bars_before_trading < self.vwap_slope_lookback_bars:
            raise ValueError(
                f"min_bars_before_trading ({self.min_bars_before_trading}) must be >= "
                f"vwap_slope_lookback_bars ({self.vwap_slope_lookback_bars})"
            )
        if self.max_trades_per_symbol_per_day < 1:
            raise ValueError(
                f"max_trades_per_symbol_per_day must be >= 1, "
                f"got {self.max_trades_per_symbol_per_day}"
            )
        if self.square_off_time <= self.no_new_entries_after:
            raise ValueError(
                f"square_off_time ({self.square_off_time}) must be after "
                f"no_new_entries_after ({self.no_new_entries_after})"
            )
        if self.no_new_entries_after <= self.no_trade_before:
            raise ValueError(
                f"no_new_entries_after ({self.no_new_entries_after}) must be after "
                f"no_trade_before ({self.no_trade_before})"
            )
        if self.confirmation_mode not in _VALID_CONFIRMATION_MODES:
            raise ValueError(
                f"confirmation_mode must be one of {_VALID_CONFIRMATION_MODES}, "
                f"got {self.confirmation_mode!r}"
            )


# ---------------------------------------------------------------------------
# Per-symbol state
# ---------------------------------------------------------------------------


@dataclass
class _SymbolState:
    """Mutable per-symbol, per-day state for VWAPTrendPullbackStrategy."""

    current_date: date | None = None
    # VWAP accumulators
    cumulative_pv: Decimal = field(default_factory=Decimal)
    cumulative_vol: int = 0
    vwap: Decimal | None = None
    vwap_history: list[Decimal] = field(default_factory=list)
    # Bar counting
    bars_seen_today: int = 0
    prev_bar_high: Decimal | None = None
    # Position tracking
    in_position: bool = False
    entry_price: Decimal | None = None
    stop_price: Decimal | None = None
    target_price: Decimal | None = None
    # Daily trade tracking
    entered_today: bool = False
    trades_taken_today: int = 0

    def __post_init__(self) -> None:
        self.cumulative_pv = Decimal("0")

    def reset(self, new_date: date) -> None:
        """Reset all intraday state for a new trading day."""
        self.current_date = new_date
        self.cumulative_pv = Decimal("0")
        self.cumulative_vol = 0
        self.vwap = None
        self.vwap_history = []
        self.bars_seen_today = 0
        self.prev_bar_high = None
        self.in_position = False
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.entered_today = False
        self.trades_taken_today = 0


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class VWAPTrendPullbackStrategy(Strategy):
    """VWAP Trend Pullback strategy (long-only, backtest v1).

    Construct with a VWAPPullbackConfig to customise all parameters.

    Example::

        config = VWAPPullbackConfig(quantity=10, stop_loss_bps=40.0)
        strategy = VWAPTrendPullbackStrategy(config=config)

    The strategy resets per-symbol state automatically on the first bar of
    each new trading date, making it correct for multi-day backtests.
    """

    def __init__(
        self,
        config: VWAPPullbackConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        cfg = config or VWAPPullbackConfig()
        super().__init__(strategy_id=cfg.strategy_id)
        self._config = cfg
        self._logger = logger or logging.getLogger(__name__)
        self._states: dict[str, _SymbolState] = {}

    # ------------------------------------------------------------------
    # Strategy interface
    # ------------------------------------------------------------------

    def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
        """Process one bar; return zero or more OrderIntents."""
        state = self._get_state(bar.symbol)
        bar_date = _bar_date(bar)
        bar_time = _bar_time(bar)

        # Reset state at the start of each new trading day.
        if state.current_date != bar_date:
            state.reset(bar_date)

        # Update VWAP with current bar's data.
        self._update_vwap(bar, state)
        state.bars_seen_today += 1

        intents: list[OrderIntent] = []

        # ── Exit checks (before entry) ───────────────────────────────────
        if state.in_position:
            exit_intent = self._check_exit(bar, bar_time, state)
            if exit_intent is not None:
                intents.append(exit_intent)
                state.in_position = False
                if self._config.allow_reentry:
                    # Allow re-entry: reset the per-entry flag, keep the count.
                    state.entered_today = False
                state.prev_bar_high = bar.high
                return intents

        # ── Entry check ──────────────────────────────────────────────────
        if self._can_enter(bar_time, state):
            entry_intent = self._check_entry(bar, state)
            if entry_intent is not None:
                intents.append(entry_intent)
                entry_price = bar.close
                cfg = self._config
                sl_factor = Decimal(str(cfg.stop_loss_bps)) / _TEN_THOUSAND
                tgt_factor = Decimal(str(cfg.target_bps)) / _TEN_THOUSAND
                state.in_position = True
                state.entered_today = True
                state.entry_price = entry_price
                state.stop_price = entry_price * (_ONE - sl_factor)
                state.target_price = entry_price * (_ONE + tgt_factor)
                state.trades_taken_today += 1

        state.prev_bar_high = bar.high
        return intents

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_state(self, symbol: str) -> _SymbolState:
        if symbol not in self._states:
            self._states[symbol] = _SymbolState()
        return self._states[symbol]

    def _update_vwap(self, bar: Bar, state: _SymbolState) -> None:
        """Update cumulative VWAP and slope history with the current bar.

        If volume is zero, use close as price contribution with weight 1 to
        avoid divide-by-zero while keeping VWAP moving.
        """
        if bar.volume > 0:
            typical_price = (bar.high + bar.low + bar.close) / _THREE
            state.cumulative_pv += typical_price * Decimal(bar.volume)
            state.cumulative_vol += bar.volume
        else:
            # Zero volume fallback: contribute close price with weight 1.
            state.cumulative_pv += bar.close
            state.cumulative_vol += 1

        state.vwap = state.cumulative_pv / Decimal(state.cumulative_vol)

        # Maintain a rolling history for slope calculation.
        state.vwap_history.append(state.vwap)
        max_history = self._config.vwap_slope_lookback_bars * 3 + 5
        if len(state.vwap_history) > max_history:
            state.vwap_history = state.vwap_history[-max_history:]

    def _vwap_slope_positive(self, state: _SymbolState) -> bool:
        """Return True if VWAP has risen over the lookback window."""
        lookback = self._config.vwap_slope_lookback_bars
        if len(state.vwap_history) < lookback:
            return False
        return state.vwap_history[-1] > state.vwap_history[-lookback]

    def _can_enter(self, bar_time: time, state: _SymbolState) -> bool:
        """Return True if entry conditions (excluding price/VWAP) are met."""
        cfg = self._config
        return (
            not state.in_position
            and not state.entered_today
            and state.trades_taken_today < cfg.max_trades_per_symbol_per_day
            and bar_time >= cfg.no_trade_before
            and bar_time <= cfg.no_new_entries_after
            and state.bars_seen_today >= cfg.min_bars_before_trading
            and state.vwap is not None
        )

    def _check_entry(self, bar: Bar, state: _SymbolState) -> OrderIntent | None:
        """Return a BUY OrderIntent if all entry conditions are satisfied."""
        vwap = state.vwap
        if vwap is None or vwap == _ZERO:
            return None

        # 1. Close must be above VWAP.
        if bar.close <= vwap:
            return None

        # 2. VWAP slope must be positive over the lookback.
        if not self._vwap_slope_positive(state):
            return None

        # 3. Pullback: bar's low must have touched near VWAP.
        tol = Decimal(str(self._config.pullback_tolerance_bps))
        pullback_ceiling = vwap * (_ONE + tol / _TEN_THOUSAND)
        if bar.low > pullback_ceiling:
            return None  # low did not reach the VWAP zone

        # 4. Confirmation.
        if not self._confirmed(bar, state):
            return None

        return OrderIntent(
            strategy_id=self.strategy_id,
            symbol=bar.symbol,
            exchange=bar.exchange,
            side="BUY",
            quantity=self._config.quantity,
            order_type="MARKET",
            product=self._config.product,
            reason="vwap_pullback_long",
        )

    def _confirmed(self, bar: Bar, state: _SymbolState) -> bool:
        """Return True if the confirmation condition is met."""
        mode = self._config.confirmation_mode
        if mode == "close_above_prior_high":
            if state.prev_bar_high is None:
                return False
            return bar.close > state.prev_bar_high
        # mode == "close_above_vwap"
        if state.vwap is None:
            return False
        return bar.close > state.vwap

    def _check_exit(self, bar: Bar, bar_time: time, state: _SymbolState) -> OrderIntent | None:
        """Return a SELL OrderIntent if any exit condition is met.

        Priority: stop-loss > target > square-off.
        """
        assert state.stop_price is not None
        assert state.target_price is not None

        # Square-off time — unconditional exit.
        if bar_time >= self._config.square_off_time:
            return self._sell_intent(bar, "vwap_square_off")

        stop_hit = bar.low <= state.stop_price
        target_hit = bar.high >= state.target_price

        if stop_hit and target_hit:
            # Conservative: assume stop was filled first.
            return self._sell_intent(bar, "vwap_stop_loss")
        if stop_hit:
            return self._sell_intent(bar, "vwap_stop_loss")
        if target_hit:
            return self._sell_intent(bar, "vwap_target")

        return None

    def _sell_intent(self, bar: Bar, reason: str) -> OrderIntent:
        return OrderIntent(
            strategy_id=self.strategy_id,
            symbol=bar.symbol,
            exchange=bar.exchange,
            side="SELL",
            quantity=self._config.quantity,
            order_type="MARKET",
            product=self._config.product,
            reason=reason,
        )


# ---------------------------------------------------------------------------
# Timestamp helpers (reuse same pattern as orb.py)
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
