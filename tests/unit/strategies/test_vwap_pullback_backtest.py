"""Integration tests: VWAP Pullback strategy running end-to-end in BacktestEngine."""

from __future__ import annotations

from datetime import time
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
from trading_engine.strategies.vwap_pullback import VWAPPullbackConfig, VWAPTrendPullbackStrategy

# ---------------------------------------------------------------------------
# Zero-cost, zero-slippage setup (isolates strategy logic from fees)
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


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------


def _make_engine(
    candles: dict[str, pd.DataFrame],
    config: VWAPPullbackConfig | None = None,
    initial_cash: Decimal = Decimal("500000"),
) -> BacktestEngine:
    cfg = config or _test_config()
    strategy = VWAPTrendPullbackStrategy(config=cfg)
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


def _test_config(**kwargs) -> VWAPPullbackConfig:
    """Config tuned for synthetic tests: small bar count, permissive conditions."""
    defaults: dict = dict(
        strategy_id="vwap_test",
        min_bars_before_trading=5,
        vwap_slope_lookback_bars=3,
        no_trade_before=time(9, 15),
        no_new_entries_after=time(14, 30),
        square_off_time=time(15, 15),
        pullback_tolerance_bps=50.0,
        confirmation_mode="close_above_vwap",
        stop_loss_bps=50.0,
        target_bps=100.0,
        quantity=10,
        allow_reentry=False,
    )
    defaults.update(kwargs)
    return VWAPPullbackConfig(**defaults)


# ---------------------------------------------------------------------------
# Synthetic data builders
# ---------------------------------------------------------------------------


def _row(ts: str, o: float, h: float, lo: float, c: float, v: int = 1000) -> dict:
    return {
        "timestamp": pd.Timestamp(ts),
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "volume": v,
    }


# Warmup bars: 5 uptrend bars so VWAP has positive slope.
# tp = close for each bar (since high=close+1, low=close-1).
# closes: 100, 102, 104, 106, 108 → VWAP after bar 5 = 104.
_UPTREND_ROWS = [
    _row("2024-01-15 09:15:00", 100, 101, 99, 100),
    _row("2024-01-15 09:16:00", 102, 103, 101, 102),
    _row("2024-01-15 09:17:00", 104, 105, 103, 104),
    _row("2024-01-15 09:18:00", 106, 107, 105, 106),
    _row("2024-01-15 09:19:00", 108, 109, 107, 108),
]


def _no_entry_df() -> pd.DataFrame:
    """Warmup bars then bars that never touch VWAP → no entry."""
    rows = _UPTREND_ROWS + [
        # Bars with low well above VWAP (~104) — no pullback.
        _row("2024-01-15 09:20:00", 110, 115, 110, 112),
        _row("2024-01-15 09:21:00", 112, 116, 111, 113),
        _row("2024-01-15 15:15:00", 113, 114, 112, 113),
    ]
    return pd.DataFrame(rows)


def _entry_then_square_off_df() -> pd.DataFrame:
    """Warmup, entry at 09:20 (pullback to VWAP, confirmation), exit at 15:15."""
    # After warmup VWAP ≈ 104.
    # Entry bar at 09:20: low=104 (at VWAP), close=105 (> VWAP=~104.167 after update).
    rows = _UPTREND_ROWS + [
        # Entry bar: low=104 ≤ VWAP*1.005, close=105 > VWAP.
        _row("2024-01-15 09:20:00", 104, 110, 104, 105),
        # Hold bars — no stop/target hit (stop≈104.475, target≈106.05).
        _row("2024-01-15 09:21:00", 105, 106, 104.5, 105.5),
        _row("2024-01-15 10:00:00", 105, 106, 104.5, 105.5),
        # Square-off bar at 15:15.
        _row("2024-01-15 15:15:00", 105, 106, 104.5, 105.5),
    ]
    return pd.DataFrame(rows)


def _entry_then_target_df() -> pd.DataFrame:
    """Warmup, entry at 09:20, target hit at 09:21.

    Entry at close=105; target = 105 * 1.01 = 106.05.
    Next bar high=107 ≥ 106.05 → target.
    """
    rows = _UPTREND_ROWS + [
        _row("2024-01-15 09:20:00", 104, 110, 104, 105),  # entry bar
        _row("2024-01-15 09:21:00", 105, 107, 104.5, 106),  # target hit (high=107 ≥ 106.05)
        _row("2024-01-15 15:15:00", 106, 107, 105, 106),  # already exited
    ]
    return pd.DataFrame(rows)


def _entry_then_stop_df() -> pd.DataFrame:
    """Warmup, entry at 09:20, stop hit at 09:21.

    Entry at close=105; stop = 105 * 0.995 = 104.475.
    Next bar low=104 ≤ 104.475 → stop.
    """
    rows = _UPTREND_ROWS + [
        _row("2024-01-15 09:20:00", 104, 110, 104, 105),  # entry bar
        _row("2024-01-15 09:21:00", 105, 106, 104, 104),  # stop hit (low=104 ≤ 104.475)
        _row("2024-01-15 15:15:00", 104, 105, 103, 104),  # already exited
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Tests: engine runs and produces a report
# ---------------------------------------------------------------------------


class TestVWAPEngineRun:
    def test_engine_runs_and_returns_report(self) -> None:
        engine = _make_engine({"RELIANCE": _no_entry_df()})
        report = engine.run()
        assert isinstance(report, BacktestReport)

    def test_report_has_correct_strategy_id(self) -> None:
        cfg = _test_config(strategy_id="vwap_check")
        engine = _make_engine({"RELIANCE": _no_entry_df()}, config=cfg)
        report = engine.run()
        assert report.strategy_id == "vwap_check"

    def test_equity_curve_is_populated(self) -> None:
        engine = _make_engine({"RELIANCE": _no_entry_df()})
        report = engine.run()
        assert len(report.equity_curve) > 0

    def test_start_and_end_time_are_set(self) -> None:
        engine = _make_engine({"RELIANCE": _no_entry_df()})
        report = engine.run()
        assert report.start_time is not None
        assert report.end_time is not None


# ---------------------------------------------------------------------------
# Tests: no-entry scenario
# ---------------------------------------------------------------------------


class TestVWAPNoEntry:
    def test_no_pullback_produces_no_fills(self) -> None:
        engine = _make_engine({"RELIANCE": _no_entry_df()})
        report = engine.run()
        assert report.fills == []

    def test_no_entry_final_equity_equals_initial(self) -> None:
        engine = _make_engine({"RELIANCE": _no_entry_df()}, initial_cash=Decimal("300000"))
        report = engine.run()
        assert report.final_equity == Decimal("300000")


# ---------------------------------------------------------------------------
# Tests: entry + square-off scenario
# ---------------------------------------------------------------------------


class TestVWAPSquareOff:
    def test_entry_produces_buy_fill(self) -> None:
        engine = _make_engine({"RELIANCE": _entry_then_square_off_df()})
        report = engine.run()
        buy_fills = [f for f in report.fills if f.side == Side.BUY]
        assert len(buy_fills) >= 1

    def test_square_off_produces_sell_fill(self) -> None:
        engine = _make_engine({"RELIANCE": _entry_then_square_off_df()})
        report = engine.run()
        sell_fills = [f for f in report.fills if f.side == Side.SELL]
        assert len(sell_fills) >= 1

    def test_entry_plus_square_off_gives_two_fills(self) -> None:
        engine = _make_engine({"RELIANCE": _entry_then_square_off_df()})
        report = engine.run()
        assert len(report.fills) == 2

    def test_buy_fill_symbol(self) -> None:
        engine = _make_engine({"RELIANCE": _entry_then_square_off_df()})
        report = engine.run()
        buy_fills = [f for f in report.fills if f.side == Side.BUY]
        assert buy_fills[0].symbol == "RELIANCE"


# ---------------------------------------------------------------------------
# Tests: profit target scenario
# ---------------------------------------------------------------------------


class TestVWAPTargetHit:
    def test_target_produces_buy_and_sell(self) -> None:
        engine = _make_engine({"RELIANCE": _entry_then_target_df()})
        report = engine.run()
        buy_fills = [f for f in report.fills if f.side == Side.BUY]
        sell_fills = [f for f in report.fills if f.side == Side.SELL]
        assert len(buy_fills) == 1
        assert len(sell_fills) == 1

    def test_target_fill_count_is_two(self) -> None:
        engine = _make_engine({"RELIANCE": _entry_then_target_df()})
        report = engine.run()
        assert len(report.fills) == 2

    def test_target_metrics_trade_count(self) -> None:
        engine = _make_engine({"RELIANCE": _entry_then_target_df()})
        report = engine.run()
        assert report.metrics.trade_count == 2


# ---------------------------------------------------------------------------
# Tests: stop-loss scenario
# ---------------------------------------------------------------------------


class TestVWAPStopLoss:
    def test_stop_loss_produces_two_fills(self) -> None:
        engine = _make_engine({"RELIANCE": _entry_then_stop_df()})
        report = engine.run()
        assert len(report.fills) == 2

    def test_stop_loss_fill_sides(self) -> None:
        engine = _make_engine({"RELIANCE": _entry_then_stop_df()})
        report = engine.run()
        assert report.fills[0].side == Side.BUY
        assert report.fills[1].side == Side.SELL


# ---------------------------------------------------------------------------
# Tests: no Zerodha / live broker dependency
# ---------------------------------------------------------------------------


class TestNoZerodhaDependency:
    def test_vwap_module_has_no_kiteconnect_import(self) -> None:
        import inspect

        import trading_engine.strategies.vwap_pullback as mod

        src = inspect.getsource(mod)
        assert "kiteconnect" not in src

    def test_vwap_module_has_no_zerodha_import(self) -> None:
        import inspect

        import trading_engine.strategies.vwap_pullback as mod

        src = inspect.getsource(mod)
        assert "zerodha" not in src.lower()

    def test_vwap_module_has_no_live_execution_import(self) -> None:
        import inspect

        import trading_engine.strategies.vwap_pullback as mod

        src = inspect.getsource(mod)
        assert "live_execution" not in src
        assert "place_order" not in src
