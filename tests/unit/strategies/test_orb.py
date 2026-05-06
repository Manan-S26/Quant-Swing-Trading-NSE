"""Unit tests for OpeningRangeBreakoutStrategy."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

import pytest

from trading_engine.strategies.orb import OpeningRangeBreakoutStrategy, ORBConfig
from trading_engine.strategy.base import StrategyContext
from trading_engine.strategy.signals import Bar

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXCHANGE = "NSE"
_SYMBOL = "RELIANCE"


def _ctx() -> StrategyContext:
    return StrategyContext(strategy_id="orb_v1", mode="backtest", config={})


def _bar(
    ts: str,
    open_: float = 500.0,
    high: float = 510.0,
    low: float = 490.0,
    close: float = 505.0,
    volume: int = 10000,
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


def _orb(
    opening_range_minutes: int = 15,
    quantity: int = 10,
    target_r_multiple: Decimal = Decimal("2"),
    stop_buffer_bps: Decimal = Decimal("0"),
    entry_buffer_bps: Decimal = Decimal("0"),
    square_off_time: time = time(15, 15),
    allow_reentry: bool = False,
) -> OpeningRangeBreakoutStrategy:
    config = ORBConfig(
        strategy_id="orb_v1",
        opening_range_minutes=opening_range_minutes,
        quantity=quantity,
        target_r_multiple=target_r_multiple,
        stop_buffer_bps=stop_buffer_bps,
        entry_buffer_bps=entry_buffer_bps,
        square_off_time=square_off_time,
        allow_reentry=allow_reentry,
    )
    return OpeningRangeBreakoutStrategy(config=config)


# Opening range bars: 09:15 to 09:29 (15-min OR)
_OR_BARS = [
    # Establish range: high=510, low=490
    _bar("2024-01-15 09:15:00", high=510.0, low=490.0),
    _bar("2024-01-15 09:16:00", high=505.0, low=495.0),
    _bar("2024-01-15 09:29:00", high=508.0, low=492.0),
]


def _feed_or(strategy: OpeningRangeBreakoutStrategy, ctx: StrategyContext) -> None:
    """Feed opening range bars to the strategy."""
    for bar in _OR_BARS:
        strategy.on_bar(bar, ctx)


# ---------------------------------------------------------------------------
# ORBConfig validation
# ---------------------------------------------------------------------------


class TestORBConfig:
    def test_valid_config(self) -> None:
        config = ORBConfig(opening_range_minutes=15, quantity=10)
        assert config.opening_range_minutes == 15
        assert config.quantity == 10

    def test_zero_opening_range_minutes_raises(self) -> None:
        with pytest.raises(ValueError, match="opening_range_minutes"):
            ORBConfig(opening_range_minutes=0)

    def test_negative_opening_range_minutes_raises(self) -> None:
        with pytest.raises(ValueError, match="opening_range_minutes"):
            ORBConfig(opening_range_minutes=-5)

    def test_zero_quantity_raises(self) -> None:
        with pytest.raises(ValueError, match="quantity"):
            ORBConfig(quantity=0)

    def test_negative_quantity_raises(self) -> None:
        with pytest.raises(ValueError, match="quantity"):
            ORBConfig(quantity=-1)

    def test_zero_target_r_multiple_raises(self) -> None:
        with pytest.raises(ValueError, match="target_r_multiple"):
            ORBConfig(target_r_multiple=Decimal("0"))

    def test_negative_target_r_multiple_raises(self) -> None:
        with pytest.raises(ValueError, match="target_r_multiple"):
            ORBConfig(target_r_multiple=Decimal("-1"))

    def test_negative_stop_buffer_raises(self) -> None:
        with pytest.raises(ValueError, match="stop_buffer_bps"):
            ORBConfig(stop_buffer_bps=Decimal("-1"))

    def test_negative_entry_buffer_raises(self) -> None:
        with pytest.raises(ValueError, match="entry_buffer_bps"):
            ORBConfig(entry_buffer_bps=Decimal("-1"))

    def test_short_selling_raises(self) -> None:
        with pytest.raises(NotImplementedError):
            ORBConfig(long_only=False)

    def test_defaults_are_valid(self) -> None:
        config = ORBConfig()
        assert config.opening_range_minutes == 15
        assert config.quantity == 1
        assert config.target_r_multiple == Decimal("2.0")
        assert config.long_only is True
        assert config.allow_reentry is False


# ---------------------------------------------------------------------------
# Opening range building
# ---------------------------------------------------------------------------


class TestOpeningRangeBuilding:
    def test_no_trade_during_opening_range(self) -> None:
        strategy = _orb()
        ctx = _ctx()
        for bar in _OR_BARS:
            intents = strategy.on_bar(bar, ctx)
            assert intents == [], f"Expected no intents during OR, got {intents}"

    def test_opening_range_high_is_max_of_bar_highs(self) -> None:
        strategy = _orb()
        ctx = _ctx()
        _feed_or(strategy, ctx)
        state = strategy._states[_SYMBOL]
        assert state.opening_range_high == Decimal("510.0")

    def test_opening_range_low_is_min_of_bar_lows(self) -> None:
        strategy = _orb()
        ctx = _ctx()
        _feed_or(strategy, ctx)
        state = strategy._states[_SYMBOL]
        assert state.opening_range_low == Decimal("490.0")

    def test_opening_range_not_complete_during_range(self) -> None:
        strategy = _orb()
        ctx = _ctx()
        _feed_or(strategy, ctx)
        state = strategy._states[_SYMBOL]
        # Range is NOT complete yet — 09:29 bar was the last one we fed.
        assert not state.opening_range_complete

    def test_opening_range_complete_after_09_30(self) -> None:
        strategy = _orb()
        ctx = _ctx()
        _feed_or(strategy, ctx)
        # Feed a bar at 09:30 (just after range end).
        strategy.on_bar(_bar("2024-01-15 09:30:00", high=505.0, low=500.0), ctx)
        state = strategy._states[_SYMBOL]
        assert state.opening_range_complete

    def test_no_breakout_bar_produces_no_intent(self) -> None:
        strategy = _orb()
        ctx = _ctx()
        _feed_or(strategy, ctx)
        # Bar at 09:30 that stays inside the range (high < 510).
        intents = strategy.on_bar(_bar("2024-01-15 09:30:00", high=508.0, low=495.0), ctx)
        assert intents == []

    def test_no_trade_if_breakout_before_range_close(self) -> None:
        """A bar at 09:20 with high above 510 should NOT trigger entry."""
        strategy = _orb()
        ctx = _ctx()
        # Start with one bar at 09:15.
        strategy.on_bar(_bar("2024-01-15 09:15:00", high=510.0, low=490.0), ctx)
        # Bar at 09:20 — still inside opening range, even if high is huge.
        intents = strategy.on_bar(_bar("2024-01-15 09:20:00", high=600.0, low=490.0), ctx)
        assert intents == []


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


class TestORBEntry:
    def test_long_breakout_emits_buy_intent(self) -> None:
        strategy = _orb()
        ctx = _ctx()
        _feed_or(strategy, ctx)
        # Breakout: high = 511 > OR high of 510.
        intents = strategy.on_bar(
            _bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx
        )
        assert len(intents) == 1
        assert intents[0].side == "BUY"

    def test_buy_intent_has_correct_symbol(self) -> None:
        strategy = _orb()
        ctx = _ctx()
        _feed_or(strategy, ctx)
        intents = strategy.on_bar(
            _bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx
        )
        assert intents[0].symbol == _SYMBOL

    def test_buy_intent_has_configured_quantity(self) -> None:
        strategy = _orb(quantity=25)
        ctx = _ctx()
        _feed_or(strategy, ctx)
        intents = strategy.on_bar(
            _bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx
        )
        assert intents[0].quantity == 25

    def test_buy_intent_is_market_order(self) -> None:
        strategy = _orb()
        ctx = _ctx()
        _feed_or(strategy, ctx)
        intents = strategy.on_bar(
            _bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx
        )
        assert intents[0].order_type == "MARKET"

    def test_buy_intent_product_is_mis(self) -> None:
        strategy = _orb()
        ctx = _ctx()
        _feed_or(strategy, ctx)
        intents = strategy.on_bar(
            _bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx
        )
        assert intents[0].product == "MIS"

    def test_buy_reason_is_orb_breakout_long(self) -> None:
        strategy = _orb()
        ctx = _ctx()
        _feed_or(strategy, ctx)
        intents = strategy.on_bar(
            _bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx
        )
        assert intents[0].reason == "orb_breakout_long"

    def test_no_short_on_downside_breakdown(self) -> None:
        strategy = _orb()
        ctx = _ctx()
        _feed_or(strategy, ctx)
        # Downside breakdown: low=480 (below OR low of 490) but high < OR high.
        intents = strategy.on_bar(_bar("2024-01-15 09:30:00", high=508.0, low=480.0), ctx)
        assert intents == []

    def test_no_entry_when_risk_is_zero(self) -> None:
        """Entry price equals stop price → risk=0 → no trade."""
        # OR: high=510, low=510 (flat range)
        strategy = _orb()
        ctx = _ctx()
        strategy.on_bar(_bar("2024-01-15 09:15:00", high=510.0, low=510.0), ctx)
        # Entry bar: close=510, OR low=510 → risk=510-510=0.
        intents = strategy.on_bar(
            _bar("2024-01-15 09:30:00", high=511.0, low=510.0, close=510.0), ctx
        )
        assert intents == []

    def test_entry_buffer_raises_trigger_level(self) -> None:
        """With entry_buffer_bps=100 (1%), trigger = 510 * 1.01 = 515.1."""
        strategy = _orb(entry_buffer_bps=Decimal("100"))
        ctx = _ctx()
        _feed_or(strategy, ctx)
        # high=514 < 515.1 → should NOT trigger.
        intents = strategy.on_bar(_bar("2024-01-15 09:30:00", high=514.0, low=495.0), ctx)
        assert intents == []

    def test_entry_buffer_triggers_at_correct_level(self) -> None:
        strategy = _orb(entry_buffer_bps=Decimal("100"))
        ctx = _ctx()
        _feed_or(strategy, ctx)
        # high=516 > 515.1 → should trigger.
        intents = strategy.on_bar(
            _bar("2024-01-15 09:30:00", high=516.0, low=495.0, close=516.0), ctx
        )
        assert len(intents) == 1
        assert intents[0].side == "BUY"

    def test_no_second_entry_after_first(self) -> None:
        """Once entered, subsequent bars should not emit another BUY."""
        strategy = _orb()
        ctx = _ctx()
        _feed_or(strategy, ctx)
        # Entry on first post-OR bar.
        strategy.on_bar(_bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx)
        # Second bar — should not re-enter.
        intents = strategy.on_bar(_bar("2024-01-15 09:31:00", high=515.0, low=505.0), ctx)
        buy_intents = [i for i in intents if i.side == "BUY"]
        assert buy_intents == []

    def test_state_reflects_in_position_after_entry(self) -> None:
        strategy = _orb()
        ctx = _ctx()
        _feed_or(strategy, ctx)
        strategy.on_bar(_bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx)
        state = strategy._states[_SYMBOL]
        assert state.in_position is True
        assert state.entered_today is True


# ---------------------------------------------------------------------------
# Exit: stop-loss
# ---------------------------------------------------------------------------


class TestORBStopLoss:
    def _enter(self) -> tuple[OpeningRangeBreakoutStrategy, StrategyContext]:
        """Feed OR bars and entry bar, return strategy in-position."""
        strategy = _orb(quantity=10, target_r_multiple=Decimal("2"))
        ctx = _ctx()
        _feed_or(strategy, ctx)
        # Entry: close=510, OR low=490, risk=510-490=20, target=510+40=550.
        strategy.on_bar(_bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx)
        return strategy, ctx

    def test_stop_loss_emits_sell(self) -> None:
        strategy, ctx = self._enter()
        # Bar where low dips to 489 ≤ stop of 490.
        intents = strategy.on_bar(_bar("2024-01-15 09:31:00", high=505.0, low=489.0), ctx)
        assert len(intents) == 1
        assert intents[0].side == "SELL"

    def test_stop_loss_reason(self) -> None:
        strategy, ctx = self._enter()
        intents = strategy.on_bar(_bar("2024-01-15 09:31:00", high=505.0, low=489.0), ctx)
        assert intents[0].reason == "orb_stop_loss"

    def test_stop_not_triggered_if_low_above_stop(self) -> None:
        strategy, ctx = self._enter()
        # Low=492 > stop of 490.
        intents = strategy.on_bar(_bar("2024-01-15 09:31:00", high=512.0, low=492.0), ctx)
        sell_intents = [i for i in intents if i.side == "SELL"]
        assert sell_intents == []

    def test_no_position_after_stop(self) -> None:
        strategy, ctx = self._enter()
        strategy.on_bar(_bar("2024-01-15 09:31:00", high=505.0, low=489.0), ctx)
        state = strategy._states[_SYMBOL]
        assert state.in_position is False


# ---------------------------------------------------------------------------
# Exit: target
# ---------------------------------------------------------------------------


class TestORBTarget:
    def _enter(self) -> tuple[OpeningRangeBreakoutStrategy, StrategyContext]:
        strategy = _orb(quantity=10, target_r_multiple=Decimal("2"))
        ctx = _ctx()
        _feed_or(strategy, ctx)
        # Entry: close=510, OR low=490, risk=20, target=550.
        strategy.on_bar(_bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx)
        return strategy, ctx

    def test_target_emits_sell(self) -> None:
        strategy, ctx = self._enter()
        # Bar where high reaches 550.
        intents = strategy.on_bar(_bar("2024-01-15 09:31:00", high=551.0, low=505.0), ctx)
        assert len(intents) == 1
        assert intents[0].side == "SELL"

    def test_target_reason(self) -> None:
        strategy, ctx = self._enter()
        intents = strategy.on_bar(_bar("2024-01-15 09:31:00", high=551.0, low=505.0), ctx)
        assert intents[0].reason == "orb_target"

    def test_target_not_triggered_if_high_below_target(self) -> None:
        strategy, ctx = self._enter()
        # High=545 < target 550.
        intents = strategy.on_bar(_bar("2024-01-15 09:31:00", high=545.0, low=505.0), ctx)
        sell_intents = [i for i in intents if i.side == "SELL"]
        assert sell_intents == []


# ---------------------------------------------------------------------------
# Exit: stop and target in same candle
# ---------------------------------------------------------------------------


class TestORBSameBarStopAndTarget:
    def test_stop_preferred_over_target_in_same_bar(self) -> None:
        strategy = _orb(quantity=10, target_r_multiple=Decimal("2"))
        ctx = _ctx()
        _feed_or(strategy, ctx)
        # Entry: close=510, stop=490, target=550.
        strategy.on_bar(_bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx)
        # Both stop (low=489) and target (high=555) hit in same bar.
        intents = strategy.on_bar(_bar("2024-01-15 09:31:00", high=555.0, low=489.0), ctx)
        assert len(intents) == 1
        assert intents[0].reason == "orb_stop_loss"


# ---------------------------------------------------------------------------
# Exit: square-off time
# ---------------------------------------------------------------------------


class TestORBSquareOff:
    def test_square_off_emits_sell(self) -> None:
        strategy = _orb(quantity=10, square_off_time=time(15, 15))
        ctx = _ctx()
        _feed_or(strategy, ctx)
        strategy.on_bar(_bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx)
        # Bar at 15:15 — should trigger square-off.
        intents = strategy.on_bar(_bar("2024-01-15 15:15:00", high=512.0, low=500.0), ctx)
        assert len(intents) == 1
        assert intents[0].side == "SELL"

    def test_square_off_reason(self) -> None:
        strategy = _orb(quantity=10, square_off_time=time(15, 15))
        ctx = _ctx()
        _feed_or(strategy, ctx)
        strategy.on_bar(_bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx)
        intents = strategy.on_bar(_bar("2024-01-15 15:15:00", high=512.0, low=500.0), ctx)
        assert intents[0].reason == "orb_square_off"

    def test_no_exit_just_before_square_off(self) -> None:
        strategy = _orb(quantity=10, square_off_time=time(15, 15))
        ctx = _ctx()
        _feed_or(strategy, ctx)
        strategy.on_bar(_bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx)
        # 15:14 — one minute before square-off, no stop/target touched.
        intents = strategy.on_bar(_bar("2024-01-15 15:14:00", high=512.0, low=505.0), ctx)
        sell_intents = [i for i in intents if i.side == "SELL"]
        assert sell_intents == []

    def test_square_off_wins_over_exit_at_same_time(self) -> None:
        """Square-off time check runs first — this is implicit in the code."""
        strategy = _orb(quantity=10, square_off_time=time(15, 15))
        ctx = _ctx()
        _feed_or(strategy, ctx)
        strategy.on_bar(_bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx)
        # Bar at 15:15 also touches stop.
        intents = strategy.on_bar(_bar("2024-01-15 15:15:00", high=512.0, low=489.0), ctx)
        assert intents[0].reason == "orb_square_off"


# ---------------------------------------------------------------------------
# Re-entry
# ---------------------------------------------------------------------------


class TestORBReentry:
    def test_no_reentry_after_stop_loss_when_disabled(self) -> None:
        strategy = _orb(allow_reentry=False)
        ctx = _ctx()
        _feed_or(strategy, ctx)
        # Enter.
        strategy.on_bar(_bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx)
        # Stop hit.
        strategy.on_bar(_bar("2024-01-15 09:31:00", high=505.0, low=489.0), ctx)
        # Another breakout — should NOT re-enter.
        intents = strategy.on_bar(
            _bar("2024-01-15 09:32:00", high=520.0, low=505.0, close=518.0), ctx
        )
        buy_intents = [i for i in intents if i.side == "BUY"]
        assert buy_intents == []

    def test_reentry_after_stop_loss_when_enabled(self) -> None:
        strategy = _orb(allow_reentry=True)
        ctx = _ctx()
        _feed_or(strategy, ctx)
        # Enter.
        strategy.on_bar(_bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx)
        # Stop hit.
        strategy.on_bar(_bar("2024-01-15 09:31:00", high=505.0, low=489.0), ctx)
        # Another breakout — CAN re-enter.
        intents = strategy.on_bar(
            _bar("2024-01-15 09:32:00", high=520.0, low=505.0, close=518.0), ctx
        )
        buy_intents = [i for i in intents if i.side == "BUY"]
        assert len(buy_intents) == 1


# ---------------------------------------------------------------------------
# Daily state reset
# ---------------------------------------------------------------------------


class TestORBDailyReset:
    def test_state_resets_on_new_day(self) -> None:
        strategy = _orb()
        ctx = _ctx()
        _feed_or(strategy, ctx)
        # Enter day 1.
        strategy.on_bar(_bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0), ctx)
        state_day1 = strategy._states[_SYMBOL]
        assert state_day1.in_position is True

        # Day 2 — first bar should reset state.
        strategy.on_bar(_bar("2024-01-16 09:15:00", high=505.0, low=495.0), ctx)
        state_day2 = strategy._states[_SYMBOL]
        assert state_day2.in_position is False
        assert state_day2.entered_today is False
        assert state_day2.opening_range_complete is False
        assert state_day2.current_date == date(2024, 1, 16)

    def test_new_day_builds_fresh_opening_range(self) -> None:
        strategy = _orb()
        ctx = _ctx()
        # Day 1 OR bars.
        _feed_or(strategy, ctx)

        # Day 2 OR: different high/low.
        strategy.on_bar(_bar("2024-01-16 09:15:00", high=600.0, low=580.0), ctx)
        state = strategy._states[_SYMBOL]
        # Day 2 opening range high should be 600, not 510 from day 1.
        assert state.opening_range_high == Decimal("600.0")
        assert state.opening_range_low == Decimal("580.0")


# ---------------------------------------------------------------------------
# Multiple symbols
# ---------------------------------------------------------------------------


class TestORBMultipleSymbols:
    def test_symbols_maintain_independent_state(self) -> None:
        strategy = _orb()
        ctx = _ctx()

        sym_a = "RELIANCE"
        sym_b = "INFY"

        # Feed OR bars for both symbols.
        for ts in ["2024-01-15 09:15:00", "2024-01-15 09:29:00"]:
            strategy.on_bar(_bar(ts, high=510.0, low=490.0, symbol=sym_a), ctx)
            strategy.on_bar(_bar(ts, high=200.0, low=180.0, symbol=sym_b), ctx)

        # Breakout for A only.
        strategy.on_bar(
            _bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0, symbol=sym_a), ctx
        )

        state_a = strategy._states[sym_a]
        state_b = strategy._states.get(sym_b)

        assert state_a.in_position is True
        # B has not broken out; should not be in position.
        if state_b is not None:
            assert state_b.in_position is False

    def test_exit_of_one_symbol_does_not_affect_other(self) -> None:
        strategy = _orb()
        ctx = _ctx()

        sym_a = "RELIANCE"
        sym_b = "INFY"

        # Feed OR bars for both.
        for ts in ["2024-01-15 09:15:00", "2024-01-15 09:29:00"]:
            strategy.on_bar(_bar(ts, high=510.0, low=490.0, symbol=sym_a), ctx)
            strategy.on_bar(_bar(ts, high=200.0, low=180.0, symbol=sym_b), ctx)

        # Both break out.
        strategy.on_bar(
            _bar("2024-01-15 09:30:00", high=511.0, low=495.0, close=510.0, symbol=sym_a), ctx
        )
        strategy.on_bar(
            _bar("2024-01-15 09:30:00", high=201.0, low=190.0, close=200.0, symbol=sym_b), ctx
        )

        # A hits stop.
        strategy.on_bar(_bar("2024-01-15 09:31:00", high=505.0, low=489.0, symbol=sym_a), ctx)

        state_a = strategy._states[sym_a]
        state_b = strategy._states[sym_b]
        assert state_a.in_position is False
        assert state_b.in_position is True
