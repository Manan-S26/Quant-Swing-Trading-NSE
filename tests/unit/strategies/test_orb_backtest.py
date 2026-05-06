"""Integration tests: ORB strategy running end-to-end in BacktestEngine."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from trading_engine.backtest.cost_model import CostModel
from trading_engine.backtest.data_feed import HistoricalDataFeed
from trading_engine.backtest.engine import BacktestEngine
from trading_engine.backtest.portfolio import BacktestPortfolio
from trading_engine.backtest.report import BacktestReport
from trading_engine.backtest.simulated_broker import SimulatedBroker
from trading_engine.backtest.slippage_model import SlippageModel
from trading_engine.domain.enums import Side
from trading_engine.strategies.orb import OpeningRangeBreakoutStrategy, ORBConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ZERO_COST = CostModel(
    brokerage_per_order=Decimal("0"),
    brokerage_cap=Decimal("0"),
    stt_rate=Decimal("0"),
    exchange_txn_rate=Decimal("0"),
    sebi_rate=Decimal("0"),
    stamp_duty_rate=Decimal("0"),
    gst_rate=Decimal("0"),
)
_ZERO_SLIP = SlippageModel(bps=Decimal("0"))


def _make_engine(
    candles: dict[str, pd.DataFrame],
    config: ORBConfig | None = None,
    initial_cash: Decimal = Decimal("500000"),
) -> BacktestEngine:
    cfg = config or ORBConfig(quantity=10)
    strategy = OpeningRangeBreakoutStrategy(config=cfg)
    portfolio = BacktestPortfolio(initial_cash=initial_cash)
    broker = SimulatedBroker(portfolio, _ZERO_COST, _ZERO_SLIP)
    feed = HistoricalDataFeed(candles)
    return BacktestEngine(
        strategy=strategy,
        data_feed=feed,
        portfolio=portfolio,
        simulated_broker=broker,
        initial_cash=initial_cash,
        strategy_id=cfg.strategy_id,
        symbols=list(candles.keys()),
    )


def _row(ts: str, o: float, h: float, lo: float, c: float, v: int = 5000) -> dict:
    return {
        "timestamp": pd.Timestamp(ts),
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "volume": v,
    }


def _no_breakout_df() -> pd.DataFrame:
    """15-min OR then bars that never break out above OR high (510)."""
    rows = [
        # Opening range (09:15–09:29): high=510, low=490
        _row("2024-01-15 09:15:00", 500, 510, 490, 500),
        _row("2024-01-15 09:20:00", 500, 508, 492, 502),
        _row("2024-01-15 09:29:00", 500, 509, 491, 501),
        # Post-OR bars — all stay below 510 high.
        _row("2024-01-15 09:30:00", 500, 509, 492, 505),
        _row("2024-01-15 09:31:00", 505, 509, 500, 504),
        _row("2024-01-15 15:15:00", 504, 506, 499, 503),
    ]
    return pd.DataFrame(rows)


def _breakout_df(close_at_entry: float = 512.0) -> pd.DataFrame:
    """Standard breakout scenario: OR high=510, breakout bar at 09:30."""
    rows = [
        _row("2024-01-15 09:15:00", 500, 510, 490, 500),
        _row("2024-01-15 09:29:00", 500, 508, 492, 502),
        # Breakout: high=511 > OR high 510.
        _row("2024-01-15 09:30:00", 500, 511, 495, close_at_entry),
        # Mid-day bars.
        _row("2024-01-15 09:31:00", 512, 515, 508, 513),
        _row("2024-01-15 10:00:00", 513, 516, 509, 514),
        # Square-off bar.
        _row("2024-01-15 15:15:00", 513, 515, 510, 513),
    ]
    return pd.DataFrame(rows)


def _target_hit_df() -> pd.DataFrame:
    """Breakout then target hit.

    OR: high=510, low=490.
    Entry at 09:30 close=512, stop=490, risk=22, target=512+44=556.
    Target bar at 09:31 has high=560 ≥ 556.
    """
    rows = [
        _row("2024-01-15 09:15:00", 500, 510, 490, 500),
        _row("2024-01-15 09:29:00", 500, 508, 492, 502),
        _row("2024-01-15 09:30:00", 500, 511, 495, 512),  # entry bar
        _row("2024-01-15 09:31:00", 512, 560, 508, 555),  # target hit
        _row("2024-01-15 15:15:00", 555, 556, 540, 550),  # should not fill (already exited)
    ]
    return pd.DataFrame(rows)


def _stop_loss_df() -> pd.DataFrame:
    """Breakout then stop-loss hit.

    OR: high=510, low=490.
    Entry at 09:30 close=512, stop=490, risk=22, target=556.
    Stop bar at 09:31 has low=488 ≤ 490.
    """
    rows = [
        _row("2024-01-15 09:15:00", 500, 510, 490, 500),
        _row("2024-01-15 09:29:00", 500, 508, 492, 502),
        _row("2024-01-15 09:30:00", 500, 511, 495, 512),  # entry bar
        _row("2024-01-15 09:31:00", 510, 515, 488, 489),  # stop hit
        _row("2024-01-15 15:15:00", 489, 492, 485, 490),  # already exited
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Engine runs and produces report
# ---------------------------------------------------------------------------


class TestORBEngineRun:
    def test_engine_runs_and_returns_report(self) -> None:
        engine = _make_engine({"RELIANCE": _no_breakout_df()})
        report = engine.run()
        assert isinstance(report, BacktestReport)

    def test_report_has_correct_strategy_id(self) -> None:
        cfg = ORBConfig(strategy_id="orb_test", quantity=5)
        engine = _make_engine({"RELIANCE": _no_breakout_df()}, config=cfg)
        report = engine.run()
        assert report.strategy_id == "orb_test"

    def test_equity_curve_is_populated(self) -> None:
        engine = _make_engine({"RELIANCE": _no_breakout_df()})
        report = engine.run()
        assert len(report.equity_curve) > 0

    def test_start_and_end_time_are_set(self) -> None:
        engine = _make_engine({"RELIANCE": _no_breakout_df()})
        report = engine.run()
        assert report.start_time is not None
        assert report.end_time is not None


# ---------------------------------------------------------------------------
# No-breakout scenario
# ---------------------------------------------------------------------------


class TestORBNoBreakout:
    def test_no_breakout_produces_no_fills(self) -> None:
        engine = _make_engine({"RELIANCE": _no_breakout_df()})
        report = engine.run()
        assert report.fills == []

    def test_no_breakout_final_equity_equals_initial(self) -> None:
        engine = _make_engine({"RELIANCE": _no_breakout_df()}, initial_cash=Decimal("200000"))
        report = engine.run()
        assert report.final_equity == Decimal("200000")


# ---------------------------------------------------------------------------
# Breakout (square-off exit) scenario
# ---------------------------------------------------------------------------


class TestORBBreakout:
    def test_breakout_produces_buy_fill(self) -> None:
        engine = _make_engine({"RELIANCE": _breakout_df()})
        report = engine.run()
        buy_fills = [f for f in report.fills if f.side == Side.BUY]
        assert len(buy_fills) >= 1

    def test_breakout_buy_fill_symbol(self) -> None:
        engine = _make_engine({"RELIANCE": _breakout_df()})
        report = engine.run()
        buy_fills = [f for f in report.fills if f.side == Side.BUY]
        assert buy_fills[0].symbol == "RELIANCE"

    def test_breakout_then_square_off_produces_sell_fill(self) -> None:
        engine = _make_engine({"RELIANCE": _breakout_df()})
        report = engine.run()
        sell_fills = [f for f in report.fills if f.side == Side.SELL]
        assert len(sell_fills) >= 1

    def test_breakout_fill_count_is_two(self) -> None:
        # One BUY (entry) + one SELL (square-off) = 2 fills.
        engine = _make_engine({"RELIANCE": _breakout_df()})
        report = engine.run()
        assert len(report.fills) == 2


# ---------------------------------------------------------------------------
# Target hit scenario
# ---------------------------------------------------------------------------


class TestORBTargetHit:
    def test_target_produces_buy_and_sell_fills(self) -> None:
        engine = _make_engine({"RELIANCE": _target_hit_df()})
        report = engine.run()
        buy_fills = [f for f in report.fills if f.side == Side.BUY]
        sell_fills = [f for f in report.fills if f.side == Side.SELL]
        assert len(buy_fills) == 1
        assert len(sell_fills) == 1

    def test_target_fill_count_is_two(self) -> None:
        engine = _make_engine({"RELIANCE": _target_hit_df()})
        report = engine.run()
        assert len(report.fills) == 2

    def test_target_metrics_trade_count(self) -> None:
        engine = _make_engine({"RELIANCE": _target_hit_df()})
        report = engine.run()
        assert report.metrics.trade_count == 2


# ---------------------------------------------------------------------------
# Stop-loss scenario
# ---------------------------------------------------------------------------


class TestORBStopLoss:
    def test_stop_loss_produces_buy_and_sell_fills(self) -> None:
        engine = _make_engine({"RELIANCE": _stop_loss_df()})
        report = engine.run()
        assert len(report.fills) == 2

    def test_stop_loss_fill_sides(self) -> None:
        engine = _make_engine({"RELIANCE": _stop_loss_df()})
        report = engine.run()
        assert report.fills[0].side == Side.BUY
        assert report.fills[1].side == Side.SELL


# ---------------------------------------------------------------------------
# No Zerodha or live broker dependency
# ---------------------------------------------------------------------------


class TestNoZerodhaDependency:
    def test_orb_module_has_no_kiteconnect_import(self) -> None:
        import inspect

        import trading_engine.strategies.orb as mod

        src = inspect.getsource(mod)
        assert "kiteconnect" not in src
        assert "ZerodhaBroker" not in src

    def test_orb_does_not_import_live_broker(self) -> None:
        import inspect

        import trading_engine.strategies.orb as mod

        src = inspect.getsource(mod)
        assert "zerodha" not in src.lower()
