"""Gap Fade to VWAP / Prior Close strategy (backtest-only, v1).

Intraday mean-reversion strategy for NSE cash equities:
  1. Detect opening gap (opening price vs previous day's closing price).
  2. If gap_bps is within [min_gap_bps, max_gap_bps], qualify the gap.
  3. After entry_start_time, enter a fade trade when price reverses
     fade_trigger_bps from the opening price (+ optional VWAP confirmation).
     Gap-up -> fade SHORT. Gap-down -> fade LONG.
  4. Exit on stop-loss, dynamic target (VWAP cross / prior close touch /
     half-gap touch), or square-off at 15:15.

No live order placement. No broker API calls. Backtest use only.

Prior close tracking
---------------------
The strategy carries the previous day's closing price across session
boundaries.  The first trading day in any dataset is always skipped because
no prior close is available.

Gap detection
-------------
  gap_bps = (opening_price / prior_close - 1) * 10000
  Gap-up  (gap_bps > 0) -> fade SHORT if allow_short_fades=True.
  Gap-down (gap_bps < 0) -> fade LONG  if allow_long_fades=True.

Entry trigger
--------------
  Gap-down long  fade: bar.close >= opening_price * (1 + fade_trigger_bps/10000)
  Gap-up  short fade: bar.close <= opening_price * (1 - fade_trigger_bps/10000)
  VWAP confirmation (require_vwap_confirmation=True):
    Long  fade: bar.close > session VWAP
    Short fade: bar.close < session VWAP

Target modes
-------------
  "vwap"        -- exit when bar crosses session VWAP (re-evaluated each bar)
  "prior_close" -- exit when bar reaches prior day's close
  "half_gap"    -- exit at midpoint of (opening_price + prior_close)
  target_bps    -- fixed-bps override; overrides target_mode when set

Exit reasons
-------------
  "gf_stop_loss"   -- stop-loss hit
  "gf_target"      -- dynamic or fixed target reached
  "gf_square_off"  -- bar timestamp >= square_off_time
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
_TWO = Decimal("2")
_THREE = Decimal("3")

_VALID_TARGET_MODES = frozenset({"vwap", "prior_close", "half_gap"})


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class GapFadeConfig:
    """Configuration for GapFadeStrategy."""

    strategy_id: str = "gap_fade_v1"
    exchange: str = "NSE"
    product: str = "MIS"
    quantity: int = 10
    session_start: time = field(default_factory=lambda: time(9, 15))
    entry_start_time: time = field(default_factory=lambda: time(9, 20))
    latest_entry_time: time = field(default_factory=lambda: time(10, 30))
    square_off_time: time = field(default_factory=lambda: time(15, 15))
    min_gap_bps: float = 60.0
    max_gap_bps: float = 300.0
    fade_trigger_bps: float = 20.0
    require_vwap_confirmation: bool = True
    target_mode: str = "vwap"
    stop_loss_bps: float = 80.0
    target_bps: float | None = None
    max_trades_per_symbol_per_day: int = 1
    allow_long_fades: bool = True
    allow_short_fades: bool = True
    min_opening_volume: int | None = None
    min_gap_abs: float | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")
        if self.min_gap_bps <= 0:
            raise ValueError(f"min_gap_bps must be positive, got {self.min_gap_bps}")
        if self.max_gap_bps <= self.min_gap_bps:
            raise ValueError(
                f"max_gap_bps ({self.max_gap_bps}) must exceed min_gap_bps ({self.min_gap_bps})"
            )
        if self.fade_trigger_bps <= 0:
            raise ValueError(f"fade_trigger_bps must be positive, got {self.fade_trigger_bps}")
        if self.stop_loss_bps <= 0:
            raise ValueError(f"stop_loss_bps must be positive, got {self.stop_loss_bps}")
        if self.target_mode not in _VALID_TARGET_MODES:
            raise ValueError(
                f"target_mode must be one of {sorted(_VALID_TARGET_MODES)}, "
                f"got {self.target_mode!r}"
            )
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
    """Mutable per-symbol state for GapFadeStrategy."""

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
    fade_direction: str = ""  # "LONG" or "SHORT"

    # Session VWAP accumulators
    cumulative_pv: Decimal = field(default_factory=lambda: Decimal("0"))
    cumulative_vol: int = 0
    vwap: Decimal | None = None

    # Position tracking
    in_position: bool = False
    position_side: str = ""  # "LONG" or "SHORT"
    entry_price: Decimal | None = None
    stop_price: Decimal | None = None
    dynamic_target: Decimal | None = None

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
        self.fade_direction = ""
        self.cumulative_pv = Decimal("0")
        self.cumulative_vol = 0
        self.vwap = None
        self.in_position = False
        self.position_side = ""
        self.entry_price = None
        self.stop_price = None
        self.dynamic_target = None
        self.bars_seen_today = 0
        self.trades_taken_today = 0


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class GapFadeStrategy(Strategy):
    """Gap Fade to VWAP / Prior Close strategy (backtest v1)."""

    def __init__(
        self,
        config: GapFadeConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        cfg = config or GapFadeConfig()
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
        self._update_vwap(bar, state)
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

    def _update_vwap(self, bar: Bar, state: _SymbolState) -> None:
        if bar.volume > 0:
            tp = (bar.high + bar.low + bar.close) / _THREE
            state.cumulative_pv += tp * Decimal(bar.volume)
            state.cumulative_vol += bar.volume
        else:
            state.cumulative_pv += bar.close
            state.cumulative_vol += 1
        state.vwap = state.cumulative_pv / Decimal(state.cumulative_vol)

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

        if cfg.min_gap_abs is not None:
            abs_price_gap = abs(state.opening_price - state.prior_close)
            if abs_price_gap < Decimal(str(cfg.min_gap_abs)):
                return

        if cfg.min_opening_volume is not None and state.opening_volume < cfg.min_opening_volume:
            return

        if gap > _ZERO and cfg.allow_short_fades:
            state.gap_qualified = True
            state.fade_direction = "SHORT"
        elif gap < _ZERO and cfg.allow_long_fades:
            state.gap_qualified = True
            state.fade_direction = "LONG"

    def _can_enter(self, bar_time: time, state: _SymbolState) -> bool:
        cfg = self._config
        return (
            state.gap_qualified
            and not state.in_position
            and state.trades_taken_today < cfg.max_trades_per_symbol_per_day
            and bar_time >= cfg.entry_start_time
            and bar_time <= cfg.latest_entry_time
            and state.vwap is not None
            and state.opening_price is not None
        )

    def _check_entry(self, bar: Bar, state: _SymbolState) -> OrderIntent | None:
        cfg = self._config
        opening = state.opening_price
        assert opening is not None
        trigger_factor = Decimal(str(cfg.fade_trigger_bps)) / _TEN_THOUSAND

        if state.fade_direction == "LONG":
            trigger_price = opening * (_ONE + trigger_factor)
            if bar.close < trigger_price:
                return None
            if cfg.require_vwap_confirmation:
                if state.vwap is None or bar.close <= state.vwap:
                    return None
            return OrderIntent(
                strategy_id=self.strategy_id,
                symbol=bar.symbol,
                exchange=bar.exchange,
                side="BUY",
                quantity=cfg.quantity,
                order_type="MARKET",
                product=cfg.product,
                reason="gf_long_entry",
            )

        if state.fade_direction == "SHORT":
            trigger_price = opening * (_ONE - trigger_factor)
            if bar.close > trigger_price:
                return None
            if cfg.require_vwap_confirmation:
                if state.vwap is None or bar.close >= state.vwap:
                    return None
            return OrderIntent(
                strategy_id=self.strategy_id,
                symbol=bar.symbol,
                exchange=bar.exchange,
                side="SELL",
                quantity=cfg.quantity,
                order_type="MARKET",
                product=cfg.product,
                reason="gf_short_entry",
            )

        return None

    def _set_position_state(self, bar: Bar, state: _SymbolState) -> None:
        entry_price = bar.close
        cfg = self._config

        state.in_position = True
        state.position_side = state.fade_direction
        state.entry_price = entry_price
        state.trades_taken_today += 1

        sl_factor = Decimal(str(cfg.stop_loss_bps)) / _TEN_THOUSAND
        if state.position_side == "LONG":
            state.stop_price = entry_price * (_ONE - sl_factor)
        else:
            state.stop_price = entry_price * (_ONE + sl_factor)

        if cfg.target_bps is not None:
            tgt_factor = Decimal(str(cfg.target_bps)) / _TEN_THOUSAND
            if state.position_side == "LONG":
                state.dynamic_target = entry_price * (_ONE + tgt_factor)
            else:
                state.dynamic_target = entry_price * (_ONE - tgt_factor)
        elif cfg.target_mode == "prior_close":
            state.dynamic_target = state.prior_close
        elif cfg.target_mode == "half_gap":
            if state.prior_close is not None and state.opening_price is not None:
                state.dynamic_target = (state.opening_price + state.prior_close) / _TWO
            else:
                state.dynamic_target = None
        else:
            # "vwap" mode: dynamic_target=None signals _check_exit to use state.vwap
            state.dynamic_target = None

    def _check_exit(self, bar: Bar, bar_time: time, state: _SymbolState) -> OrderIntent | None:
        assert state.stop_price is not None
        cfg = self._config

        if state.position_side == "LONG":
            stop_hit = bar.low <= state.stop_price
        else:
            stop_hit = bar.high >= state.stop_price

        target_hit = False
        if cfg.target_bps is not None and state.dynamic_target is not None:
            if state.position_side == "LONG":
                target_hit = bar.high >= state.dynamic_target
            else:
                target_hit = bar.low <= state.dynamic_target
        elif cfg.target_mode == "vwap" and state.vwap is not None:
            if state.position_side == "LONG":
                target_hit = bar.high >= state.vwap
            else:
                target_hit = bar.low <= state.vwap
        elif cfg.target_mode in ("prior_close", "half_gap") and state.dynamic_target is not None:
            if state.position_side == "LONG":
                target_hit = bar.high >= state.dynamic_target
            else:
                target_hit = bar.low <= state.dynamic_target

        square_off_hit = bar_time >= cfg.square_off_time

        if stop_hit:
            return self._exit_intent(bar, state, "gf_stop_loss")
        if target_hit:
            return self._exit_intent(bar, state, "gf_target")
        if square_off_hit:
            return self._exit_intent(bar, state, "gf_square_off")
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
