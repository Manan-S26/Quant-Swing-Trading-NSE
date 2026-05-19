"""Unit tests for VWAPTrendPullbackStrategy."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

import pytest

from trading_engine.strategies.vwap_pullback import VWAPPullbackConfig, VWAPTrendPullbackStrategy
from trading_engine.strategy.base import StrategyContext
from trading_engine.strategy.signals import Bar

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXCHANGE = "NSE"
_SYMBOL = "RELIANCE"


def _ctx() -> StrategyContext:
    return StrategyContext(strategy_id="vwap_test", mode="backtest", config={})


def _bar(
    ts: str,
    open_: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.0,
    volume: int = 1000,
    symbol: str = _SYMBOL,
) -> Bar:
    return Bar(
        symbol=symbol,
        exchange=_EXCHANGE,
        timestamp=datetime.fromisoformat(ts),
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=volume,
        interval="minute",
    )


def _cfg(**kwargs) -> VWAPPullbackConfig:
    """Permissive test config with small min_bars so tests don't need 15 warmup bars."""
    defaults: dict = dict(
        min_bars_before_trading=5,
        vwap_slope_lookback_bars=3,
        no_trade_before=time(9, 15),
        no_new_entries_after=time(14, 30),
        square_off_time=time(15, 15),
        pullback_tolerance_bps=50.0,
        confirmation_mode="close_above_vwap",
        stop_loss_bps=50.0,
        target_bps=100.0,
        max_trades_per_symbol_per_day=1,
        quantity=10,
        allow_reentry=False,
    )
    defaults.update(kwargs)
    return VWAPPullbackConfig(**defaults)


def _strategy(**cfg_kwargs) -> VWAPTrendPullbackStrategy:
    return VWAPTrendPullbackStrategy(config=_cfg(**cfg_kwargs))


# Bars where high = close + 1, low = close - 1 so tp = close → VWAP = avg(closes).
# Uptrend: VWAP rises each bar, establishing positive slope.
_UPTREND_CLOSES = [100, 102, 104, 106, 108]
_UPTREND_TIMES = [
    "2024-01-15 09:15:00",
    "2024-01-15 09:16:00",
    "2024-01-15 09:17:00",
    "2024-01-15 09:18:00",
    "2024-01-15 09:19:00",
]


def _uptrend_bar(i: int) -> Bar:
    c = _UPTREND_CLOSES[i]
    return _bar(_UPTREND_TIMES[i], open_=c, high=c + 1, low=c - 1, close=c)


def _feed_warmup(strategy: VWAPTrendPullbackStrategy, ctx: StrategyContext) -> None:
    """Feed 5 uptrend bars (no entry expected)."""
    for i in range(5):
        strategy.on_bar(_uptrend_bar(i), ctx)


# After 5 uptrend bars (closes 100,102,104,106,108, vol=1000 each):
# tp_i = close_i (since high=close+1, low=close-1 → tp=(h+l+c)/3=c)
# VWAP = (100+102+104+106+108)*1000 / (5*1000) = 520/5 = 104.0
_VWAP_AFTER_WARMUP = Decimal("104")


# ---------------------------------------------------------------------------
# Tests: VWAPPullbackConfig validation
# ---------------------------------------------------------------------------


class TestVWAPPullbackConfig:
    def test_default_config_is_valid(self):
        cfg = VWAPPullbackConfig()
        assert cfg.quantity == 10
        assert cfg.strategy_id == "vwap_pullback_v1"

    def test_invalid_quantity_raises(self):
        with pytest.raises(ValueError, match="quantity"):
            VWAPPullbackConfig(quantity=0)

    def test_negative_quantity_raises(self):
        with pytest.raises(ValueError):
            VWAPPullbackConfig(quantity=-1)

    def test_invalid_stop_loss_bps_raises(self):
        with pytest.raises(ValueError, match="stop_loss_bps"):
            VWAPPullbackConfig(stop_loss_bps=0.0)

    def test_invalid_target_bps_raises(self):
        with pytest.raises(ValueError, match="target_bps"):
            VWAPPullbackConfig(target_bps=0.0)

    def test_negative_pullback_tolerance_raises(self):
        with pytest.raises(ValueError, match="pullback_tolerance_bps"):
            VWAPPullbackConfig(pullback_tolerance_bps=-1.0)

    def test_zero_pullback_tolerance_is_valid(self):
        cfg = VWAPPullbackConfig(pullback_tolerance_bps=0.0)
        assert cfg.pullback_tolerance_bps == 0.0

    def test_vwap_slope_lookback_bars_zero_raises(self):
        with pytest.raises(ValueError, match="vwap_slope_lookback_bars"):
            VWAPPullbackConfig(vwap_slope_lookback_bars=0)

    def test_min_bars_less_than_lookback_raises(self):
        with pytest.raises(ValueError, match="min_bars_before_trading"):
            VWAPPullbackConfig(vwap_slope_lookback_bars=10, min_bars_before_trading=5)

    def test_max_trades_zero_raises(self):
        with pytest.raises(ValueError, match="max_trades_per_symbol_per_day"):
            VWAPPullbackConfig(max_trades_per_symbol_per_day=0)

    def test_square_off_before_no_new_entries_raises(self):
        with pytest.raises(ValueError, match="square_off_time"):
            VWAPPullbackConfig(
                no_new_entries_after=time(14, 30),
                square_off_time=time(14, 0),
            )

    def test_no_new_entries_before_no_trade_before_raises(self):
        with pytest.raises(ValueError, match="no_new_entries_after"):
            VWAPPullbackConfig(
                no_trade_before=time(10, 0),
                no_new_entries_after=time(9, 30),
                square_off_time=time(15, 15),
            )

    def test_invalid_confirmation_mode_raises(self):
        with pytest.raises(ValueError, match="confirmation_mode"):
            VWAPPullbackConfig(confirmation_mode="invalid_mode")

    def test_valid_confirmation_modes(self):
        cfg1 = VWAPPullbackConfig(confirmation_mode="close_above_prior_high")
        cfg2 = VWAPPullbackConfig(confirmation_mode="close_above_vwap")
        assert cfg1.confirmation_mode == "close_above_prior_high"
        assert cfg2.confirmation_mode == "close_above_vwap"


# ---------------------------------------------------------------------------
# Tests: VWAP calculation
# ---------------------------------------------------------------------------


class TestVWAPCalculation:
    def test_vwap_after_single_bar(self):
        s = _strategy()
        ctx = _ctx()
        # tp = (101 + 99 + 100) / 3 = 100; vol=1000 → VWAP=100
        s.on_bar(_bar("2024-01-15 09:15:00", high=101, low=99, close=100, volume=1000), ctx)
        state = s._states[_SYMBOL]
        assert state.vwap == pytest.approx(Decimal("100"), rel=Decimal("0.001"))

    def test_vwap_is_volume_weighted(self):
        s = _strategy()
        ctx = _ctx()
        # Bar 1: tp=100 (h=101,l=99,c=100), vol=1000 → pv=100000
        # Bar 2: tp=200 (h=201,l=199,c=200), vol=1 → pv=200
        # VWAP = 100200 / 1001 ≈ 100.1
        s.on_bar(_bar("2024-01-15 09:15:00", high=101, low=99, close=100, volume=1000), ctx)
        s.on_bar(_bar("2024-01-15 09:16:00", high=201, low=199, close=200, volume=1), ctx)
        state = s._states[_SYMBOL]
        expected = Decimal("100200") / Decimal("1001")
        assert state.vwap == pytest.approx(expected, rel=Decimal("0.001"))

    def test_vwap_zero_volume_does_not_crash(self):
        s = _strategy()
        ctx = _ctx()
        # volume=0 → use close=100 as tp with weight 1
        s.on_bar(_bar("2024-01-15 09:15:00", close=100, volume=0), ctx)
        state = s._states[_SYMBOL]
        assert state.vwap is not None
        assert state.vwap == pytest.approx(Decimal("100"), rel=Decimal("0.001"))

    def test_vwap_zero_volume_followed_by_real_volume(self):
        s = _strategy()
        ctx = _ctx()
        s.on_bar(_bar("2024-01-15 09:15:00", high=101, low=99, close=100, volume=0), ctx)
        s.on_bar(_bar("2024-01-15 09:16:00", high=111, low=109, close=110, volume=1000), ctx)
        state = s._states[_SYMBOL]
        assert state.vwap is not None  # no crash

    def test_vwap_history_grows_with_bars(self):
        s = _strategy()
        ctx = _ctx()
        for i in range(4):
            s.on_bar(_bar(f"2024-01-15 09:1{i}:00"), ctx)
        state = s._states[_SYMBOL]
        assert len(state.vwap_history) == 4

    def test_vwap_resets_on_new_day(self):
        s = _strategy()
        ctx = _ctx()
        # Day 1
        s.on_bar(_bar("2024-01-15 09:15:00", close=200, volume=5000), ctx)
        state = s._states[_SYMBOL]
        vwap_day1 = state.vwap

        # Day 2 — first bar resets state
        s.on_bar(_bar("2024-01-16 09:15:00", close=100, volume=1000), ctx)
        vwap_day2 = state.vwap

        assert vwap_day1 != vwap_day2
        assert state.bars_seen_today == 1
        assert state.cumulative_vol == 1000  # only current day's volume

    def test_bars_seen_resets_on_new_day(self):
        s = _strategy()
        ctx = _ctx()
        for i in range(5):
            s.on_bar(_bar(f"2024-01-15 09:1{i}:00"), ctx)
        # Day 2
        s.on_bar(_bar("2024-01-16 09:15:00"), ctx)
        state = s._states[_SYMBOL]
        assert state.bars_seen_today == 1

    def test_entered_today_resets_on_new_day(self):
        s = _strategy()
        ctx = _ctx()
        # Force entered_today to True
        state = s._get_state(_SYMBOL)
        state.current_date = date(2024, 1, 15)
        state.entered_today = True
        # New day bar
        s.on_bar(_bar("2024-01-16 09:15:00"), ctx)
        assert state.entered_today is False


# ---------------------------------------------------------------------------
# Tests: no-trade guard conditions
# ---------------------------------------------------------------------------


class TestNoTradeConditions:
    def test_no_trade_before_no_trade_before_time(self):
        """No entry emitted when bar time < no_trade_before."""
        s = _strategy(
            no_trade_before=time(9, 30), min_bars_before_trading=1, vwap_slope_lookback_bars=1
        )
        ctx = _ctx()
        # Bar at 09:15 is before no_trade_before=09:30
        intents = s.on_bar(_bar("2024-01-15 09:15:00", high=200, low=100, close=105), ctx)
        assert intents == []

    def test_no_trade_before_min_bars(self):
        """No entry when bars_seen_today < min_bars_before_trading."""
        s = _strategy(min_bars_before_trading=5, no_trade_before=time(9, 15))
        ctx = _ctx()
        # Only 3 bars — not enough
        for i in range(3):
            intents = s.on_bar(_uptrend_bar(i), ctx)
            assert intents == []

    def test_no_trade_when_close_below_vwap(self):
        """No entry when bar.close is at or below VWAP."""
        s = _strategy()
        ctx = _ctx()
        _feed_warmup(s, ctx)
        # VWAP ≈ 104 after warmup. Bar with close=103 < VWAP.
        intents = s.on_bar(_bar("2024-01-15 09:20:00", high=105, low=103, close=103), ctx)
        assert intents == []

    def test_no_trade_when_vwap_slope_flat(self):
        """No entry when VWAP slope is flat (all closes equal)."""
        s = _strategy(pullback_tolerance_bps=200.0)
        ctx = _ctx()
        # Feed 5 bars with identical close so VWAP history is flat.
        for _i, ts in enumerate(_UPTREND_TIMES):
            s.on_bar(_bar(ts, high=101, low=99, close=100), ctx)
        state = s._states[_SYMBOL]
        assert state.vwap == pytest.approx(Decimal("100"), rel=Decimal("0.001"))
        # Directly verify slope check returns False on the flat history.
        assert not s._vwap_slope_positive(state)
        # A bar with close == VWAP doesn't pass "close > vwap" → no entry.
        intents = s.on_bar(_bar("2024-01-15 09:20:00", high=101, low=99, close=100), ctx)
        assert intents == []

    def test_no_trade_when_vwap_slope_negative(self):
        """No entry when VWAP is trending down."""
        s = _strategy(pullback_tolerance_bps=200.0)
        ctx = _ctx()
        # Feed 5 bars with decreasing closes → VWAP trends down.
        downtrend_closes = [108, 106, 104, 102, 100]
        for i, ts in enumerate(_UPTREND_TIMES):
            c = downtrend_closes[i]
            s.on_bar(_bar(ts, high=c + 1, low=c - 1, close=c), ctx)
        intents = s.on_bar(_bar("2024-01-15 09:20:00", high=102, low=100, close=101), ctx)
        assert intents == []

    def test_no_trade_when_low_does_not_reach_vwap_zone(self):
        """No entry when bar.low is well above VWAP (no pullback)."""
        s = _strategy(pullback_tolerance_bps=10.0)  # tight tolerance
        ctx = _ctx()
        _feed_warmup(s, ctx)
        # VWAP ≈ 104. Bar with low=110 (far above VWAP*1.001=104.1) → no pullback.
        intents = s.on_bar(_bar("2024-01-15 09:20:00", high=115, low=110, close=112), ctx)
        assert intents == []

    def test_no_trade_after_no_new_entries_after(self):
        """No entry at or after no_new_entries_after time."""
        s = _strategy(no_new_entries_after=time(14, 30))
        ctx = _ctx()
        _feed_warmup(s, ctx)
        # A bar at 14:31 is past the entry cutoff.
        intents = s.on_bar(_bar("2024-01-15 14:31:00", high=106, low=104, close=105), ctx)
        assert intents == []

    def test_no_trade_when_not_enough_history_for_slope(self):
        """No entry when vwap_history has fewer than lookback bars."""
        s = _strategy(vwap_slope_lookback_bars=10, min_bars_before_trading=10)
        ctx = _ctx()
        # Only 5 bars → history length 5 < lookback 10 → slope returns False.
        _feed_warmup(s, ctx)
        intents = s.on_bar(_bar("2024-01-15 09:20:00", high=110, low=104, close=105), ctx)
        assert intents == []


# ---------------------------------------------------------------------------
# Tests: entry logic
# ---------------------------------------------------------------------------


class TestEntryLogic:
    def test_entry_emits_buy_intent(self):
        """Entry bar meeting all conditions emits a BUY OrderIntent."""
        s = _strategy()
        ctx = _ctx()
        _feed_warmup(s, ctx)
        # VWAP ≈ 104. Bar: low=104 (touches VWAP), close=105 (> VWAP).
        intents = s.on_bar(_bar("2024-01-15 09:20:00", high=110, low=104, close=105), ctx)
        assert len(intents) == 1
        assert intents[0].side == "BUY"
        assert intents[0].symbol == _SYMBOL

    def test_entry_intent_is_market_order(self):
        s = _strategy()
        ctx = _ctx()
        _feed_warmup(s, ctx)
        intents = s.on_bar(_bar("2024-01-15 09:20:00", high=110, low=104, close=105), ctx)
        assert intents[0].order_type == "MARKET"

    def test_entry_intent_quantity(self):
        s = _strategy(quantity=7)
        ctx = _ctx()
        _feed_warmup(s, ctx)
        intents = s.on_bar(_bar("2024-01-15 09:20:00", high=110, low=104, close=105), ctx)
        assert intents[0].quantity == 7

    def test_entry_sets_in_position(self):
        s = _strategy()
        ctx = _ctx()
        _feed_warmup(s, ctx)
        s.on_bar(_bar("2024-01-15 09:20:00", high=110, low=104, close=105), ctx)
        state = s._states[_SYMBOL]
        assert state.in_position is True

    def test_entry_sets_stop_and_target(self):
        s = _strategy(stop_loss_bps=50.0, target_bps=100.0)
        ctx = _ctx()
        _feed_warmup(s, ctx)
        s.on_bar(_bar("2024-01-15 09:20:00", high=110, low=104, close=105), ctx)
        state = s._states[_SYMBOL]
        entry = Decimal("105")
        expected_stop = entry * (1 - Decimal("50") / Decimal("10000"))
        expected_target = entry * (1 + Decimal("100") / Decimal("10000"))
        assert state.stop_price == pytest.approx(expected_stop, rel=Decimal("0.001"))
        assert state.target_price == pytest.approx(expected_target, rel=Decimal("0.001"))

    def test_no_second_entry_when_max_trades_is_one(self):
        """After one entry, no further entry allowed (max_trades_per_symbol_per_day=1)."""
        s = _strategy(max_trades_per_symbol_per_day=1, allow_reentry=False)
        ctx = _ctx()
        _feed_warmup(s, ctx)
        # First entry
        s.on_bar(_bar("2024-01-15 09:20:00", high=110, low=104, close=105), ctx)
        # Exit (stop)
        state = s._states[_SYMBOL]
        state.in_position = False
        state.entered_today = True  # stays True when allow_reentry=False
        # Try second entry — should be blocked
        intents = s.on_bar(_bar("2024-01-15 09:21:00", high=110, low=104, close=105), ctx)
        assert intents == []

    def test_confirmation_mode_close_above_prior_high(self):
        """close_above_prior_high: entry only when close > previous bar's high."""
        s = _strategy(confirmation_mode="close_above_prior_high")
        ctx = _ctx()
        _feed_warmup(s, ctx)
        # After warmup, prev_bar_high = 109 (bar 5: close=108, high=109).
        # Entry bar: close=108 < prev_bar_high=109 → no entry.
        intents = s.on_bar(_bar("2024-01-15 09:20:00", high=110, low=104, close=108), ctx)
        assert intents == []

    def test_confirmation_mode_close_above_prior_high_succeeds(self):
        """close_above_prior_high: entry occurs when close > previous bar's high."""
        s = _strategy(confirmation_mode="close_above_prior_high")
        ctx = _ctx()
        _feed_warmup(s, ctx)
        # After warmup, prev_bar_high = 109 (bar 5: close=108, high=109).
        # Entry bar: close=110 > prev_bar_high=109 ✓, low=104 near VWAP ✓.
        intents = s.on_bar(_bar("2024-01-15 09:20:00", high=115, low=104, close=110), ctx)
        assert len(intents) == 1
        assert intents[0].side == "BUY"

    def test_no_entry_when_confirmation_first_bar_no_prev_high(self):
        """close_above_prior_high mode: no entry on very first bar (no prev_bar_high)."""
        s = _strategy(
            confirmation_mode="close_above_prior_high",
            min_bars_before_trading=1,
            vwap_slope_lookback_bars=1,
            no_trade_before=time(9, 15),
        )
        ctx = _ctx()
        # First bar: no prev_bar_high → confirmation fails.
        intents = s.on_bar(_bar("2024-01-15 09:15:00", high=110, low=99, close=105), ctx)
        assert intents == []


# ---------------------------------------------------------------------------
# Tests: exit logic
# ---------------------------------------------------------------------------


class TestExitLogic:
    def _enter(self, strategy: VWAPTrendPullbackStrategy, ctx: StrategyContext) -> None:
        """Feed warmup bars then trigger entry."""
        _feed_warmup(strategy, ctx)
        strategy.on_bar(_bar("2024-01-15 09:20:00", high=110, low=104, close=105), ctx)
        state = strategy._states[_SYMBOL]
        assert state.in_position is True

    def test_stop_loss_emits_sell(self):
        s = _strategy(stop_loss_bps=50.0)  # stop = 105 * 0.995 = 104.475
        ctx = _ctx()
        self._enter(s, ctx)
        # Bar with low=104 ≤ stop_price=104.475 → stop hit.
        intents = s.on_bar(_bar("2024-01-15 09:21:00", high=106, low=104, close=104), ctx)
        assert len(intents) == 1
        assert intents[0].side == "SELL"
        assert intents[0].reason == "vwap_stop_loss"

    def test_stop_loss_clears_position(self):
        s = _strategy(stop_loss_bps=50.0)
        ctx = _ctx()
        self._enter(s, ctx)
        s.on_bar(_bar("2024-01-15 09:21:00", high=106, low=104, close=104), ctx)
        assert s._states[_SYMBOL].in_position is False

    def test_profit_target_emits_sell(self):
        s = _strategy(target_bps=100.0)  # target = 105 * 1.01 = 106.05
        ctx = _ctx()
        self._enter(s, ctx)
        # Bar with high=107 ≥ target=106.05 → target hit.
        intents = s.on_bar(_bar("2024-01-15 09:21:00", high=107, low=105, close=106), ctx)
        assert len(intents) == 1
        assert intents[0].side == "SELL"
        assert intents[0].reason == "vwap_target"

    def test_profit_target_clears_position(self):
        s = _strategy(target_bps=100.0)
        ctx = _ctx()
        self._enter(s, ctx)
        s.on_bar(_bar("2024-01-15 09:21:00", high=107, low=105, close=106), ctx)
        assert s._states[_SYMBOL].in_position is False

    def test_square_off_emits_sell(self):
        s = _strategy(square_off_time=time(15, 15))
        ctx = _ctx()
        self._enter(s, ctx)
        # Bar at 15:15 → square-off.
        intents = s.on_bar(_bar("2024-01-15 15:15:00", high=106, low=104, close=105), ctx)
        assert len(intents) == 1
        assert intents[0].side == "SELL"
        assert intents[0].reason == "vwap_square_off"

    def test_square_off_clears_position(self):
        s = _strategy()
        ctx = _ctx()
        self._enter(s, ctx)
        s.on_bar(_bar("2024-01-15 15:15:00", high=106, low=104, close=105), ctx)
        assert s._states[_SYMBOL].in_position is False

    def test_stop_takes_priority_over_target_on_same_bar(self):
        """When both stop and target are hit on the same bar, stop wins."""
        s = _strategy(stop_loss_bps=50.0, target_bps=100.0)
        ctx = _ctx()
        self._enter(s, ctx)
        # Entry at 105; stop=104.475, target=106.05.
        # Bar: low=104 ≤ stop AND high=107 ≥ target → stop priority.
        intents = s.on_bar(_bar("2024-01-15 09:21:00", high=107, low=104, close=105), ctx)
        assert intents[0].reason == "vwap_stop_loss"

    def test_square_off_takes_priority_over_stop(self):
        """Square-off time takes priority over all other exit checks."""
        s = _strategy(stop_loss_bps=50.0, square_off_time=time(15, 15))
        ctx = _ctx()
        self._enter(s, ctx)
        # Bar at square-off time with low below stop.
        intents = s.on_bar(_bar("2024-01-15 15:15:00", high=104, low=100, close=102), ctx)
        assert intents[0].reason == "vwap_square_off"

    def test_no_exit_intent_when_price_between_stop_and_target(self):
        s = _strategy(stop_loss_bps=50.0, target_bps=100.0)
        ctx = _ctx()
        self._enter(s, ctx)
        # Entry at 105; stop=104.475, target=106.05.
        # Bar: low=105, high=106 → neither stop nor target hit.
        intents = s.on_bar(_bar("2024-01-15 09:21:00", high=106, low=105, close=105.5), ctx)
        assert intents == []


# ---------------------------------------------------------------------------
# Tests: allow_reentry
# ---------------------------------------------------------------------------


class TestAllowReentry:
    def test_allow_reentry_false_blocks_second_entry(self):
        s = _strategy(allow_reentry=False, max_trades_per_symbol_per_day=2)
        ctx = _ctx()
        _feed_warmup(s, ctx)
        # First entry
        s.on_bar(_bar("2024-01-15 09:20:00", high=110, low=104, close=105), ctx)
        # Trigger exit via stop
        s.on_bar(_bar("2024-01-15 09:21:00", high=106, low=100, close=101), ctx)
        # Try re-entry — should be blocked (entered_today=True, allow_reentry=False)
        intents = s.on_bar(_bar("2024-01-15 09:22:00", high=110, low=104, close=105), ctx)
        assert intents == []

    def test_allow_reentry_true_permits_second_entry(self):
        s = _strategy(allow_reentry=True, max_trades_per_symbol_per_day=2)
        ctx = _ctx()
        _feed_warmup(s, ctx)
        # First entry at 09:20 (VWAP≈104 after warmup).
        s.on_bar(_bar("2024-01-15 09:20:00", high=110, low=104, close=105), ctx)
        assert s._states[_SYMBOL].in_position is True
        # Exit bar at 09:21: low=104 ≤ stop=104.475 → stop hit.
        # Use close=109 (keeps VWAP rising) so VWAP slope stays positive.
        s.on_bar(_bar("2024-01-15 09:21:00", high=110, low=104, close=109), ctx)
        assert s._states[_SYMBOL].in_position is False
        # entered_today was reset because allow_reentry=True.
        assert s._states[_SYMBOL].entered_today is False
        # Second entry: VWAP≈104.86 after exit bar; re-entry bar close=106>VWAP,
        # low=104 in VWAP zone, slope positive (104.86>104.39).
        intents = s.on_bar(_bar("2024-01-15 09:22:00", high=110, low=104, close=106), ctx)
        assert len(intents) == 1
        assert intents[0].side == "BUY"

    def test_allow_reentry_true_respects_max_trades(self):
        s = _strategy(allow_reentry=True, max_trades_per_symbol_per_day=1)
        ctx = _ctx()
        _feed_warmup(s, ctx)
        # First entry
        s.on_bar(_bar("2024-01-15 09:20:00", high=110, low=104, close=105), ctx)
        # Exit
        s.on_bar(_bar("2024-01-15 09:21:00", high=106, low=100, close=101), ctx)
        # trades_taken_today=1 >= max=1 → blocked
        intents = s.on_bar(_bar("2024-01-15 09:22:00", high=110, low=104, close=105), ctx)
        assert intents == []


# ---------------------------------------------------------------------------
# Tests: multi-symbol independence
# ---------------------------------------------------------------------------


class TestMultipleSymbols:
    def test_states_are_independent_per_symbol(self):
        s = _strategy()
        ctx = _ctx()
        # Feed warmup for RELIANCE
        _feed_warmup(s, ctx)
        s.on_bar(_bar("2024-01-15 09:20:00", high=110, low=104, close=105), ctx)
        # INFY state should be clean
        infy_state = s._get_state("INFY")
        assert infy_state.in_position is False
        assert infy_state.vwap is None

    def test_entry_on_one_symbol_does_not_affect_other(self):
        s = _strategy()
        ctx = _ctx()
        _feed_warmup(s, ctx)
        s.on_bar(_bar("2024-01-15 09:20:00", high=110, low=104, close=105), ctx)
        reliance_state = s._states[_SYMBOL]
        assert reliance_state.in_position is True
        # INFY: no bars fed, not in position
        infy_bar = _bar(
            "2024-01-15 09:20:00",
            high=110,
            low=104,
            close=105,
            symbol="INFY",
        )
        intents = s.on_bar(infy_bar, ctx)
        # INFY has only 1 bar → bars_seen=1 < min_bars=5 → no entry
        assert intents == []
