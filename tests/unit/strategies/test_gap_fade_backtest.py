"""Integration tests: GapFadeStrategy running end-to-end in BacktestEngine."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from trading_engine.backtest.cost_model import CostModel  # noqa: E402
from trading_engine.backtest.data_feed import HistoricalDataFeed  # noqa: E402
from trading_engine.backtest.engine import BacktestEngine  # noqa: E402
from trading_engine.backtest.portfolio import BacktestPortfolio  # noqa: E402
from trading_engine.backtest.simulated_broker import SimulatedBroker  # noqa: E402
from trading_engine.backtest.slippage_model import SlippageModel  # noqa: E402
from trading_engine.strategies.gap_fade import GapFadeConfig, GapFadeStrategy  # noqa: E402

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
    config: GapFadeConfig | None = None,
    initial_cash: Decimal = Decimal("500000"),
) -> BacktestEngine:
    cfg = config or GapFadeConfig()
    strategy = GapFadeStrategy(config=cfg)
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
        parameters={},
    )


def _make_gap_fade_candles() -> pd.DataFrame:
    """Two-day candle sequence that produces one gap-fade long trade.

    Day 1 (2024-01-15): single bar, close=107 (prior_close for day 2).
    Day 2 (2024-01-16):
      09:15 — opening bar: open=100 (~654 bps gap-down, within [50, 1000]).
               fade_direction="LONG", gap_qualified=True.
      09:20 — entry bar: close=100.5 >= trigger=100*(1+0.001)=100.1 -> LONG entry.
               require_vwap_confirmation=False (config).
      09:25–15:10 — bars that don't hit stop (stop=100.5*(1-0.02)=98.49) or
                    prior_close target (high>=107).
      15:15 — square-off bar.
    """
    rows = []
    # Day 1: single bar, close=107
    rows.append(
        {
            "timestamp": pd.Timestamp("2024-01-15 09:15:00"),
            "open": 107.0,
            "high": 107.5,
            "low": 106.5,
            "close": 107.0,
            "volume": 5000,
        }
    )
    # Day 2 opening bar: gap-down to 100
    rows.append(
        {
            "timestamp": pd.Timestamp("2024-01-16 09:15:00"),
            "open": 100.0,
            "high": 100.5,
            "low": 99.5,
            "close": 100.0,
            "volume": 5000,
        }
    )
    # 09:20 — LONG entry: close=100.5 >= trigger=100.1
    rows.append(
        {
            "timestamp": pd.Timestamp("2024-01-16 09:20:00"),
            "open": 100.0,
            "high": 100.6,
            "low": 99.8,
            "close": 100.5,
            "volume": 3000,
        }
    )
    # 09:30–15:10: bars that don't hit stop (<98.49) or target (prior_close=107, long target = high>=107)
    for h in range(9, 15):
        for m in [30, 45]:
            rows.append(
                {
                    "timestamp": pd.Timestamp(f"2024-01-16 {h:02d}:{m:02d}:00"),
                    "open": 101.0,
                    "high": 101.5,
                    "low": 100.5,
                    "close": 101.0,
                    "volume": 2000,
                }
            )
    # 15:15 — square-off
    rows.append(
        {
            "timestamp": pd.Timestamp("2024-01-16 15:15:00"),
            "open": 101.0,
            "high": 101.2,
            "low": 100.8,
            "close": 101.0,
            "volume": 1000,
        }
    )
    return pd.DataFrame(rows)


def _test_cfg() -> GapFadeConfig:
    return GapFadeConfig(
        strategy_id="gf_test",
        min_gap_bps=50.0,
        max_gap_bps=1000.0,
        fade_trigger_bps=10.0,
        stop_loss_bps=200.0,
        target_mode="prior_close",
        require_vwap_confirmation=False,
        allow_short_fades=True,
        allow_long_fades=True,
    )


class TestGapFadeBacktest:
    def test_engine_runs_without_error(self):
        df = _make_gap_fade_candles()
        engine = _make_engine({"TEST": df}, config=_test_cfg())
        report = engine.run()
        assert report is not None

    def test_at_least_two_fills_produced(self):
        """Fixture produces a long fade entry + square-off exit."""
        df = _make_gap_fade_candles()
        engine = _make_engine({"TEST": df}, config=_test_cfg())
        report = engine.run()
        assert len(report.fills) >= 2, "expected entry + exit fills"

    def test_fills_are_buy_entry_then_sell_exit(self):
        """First fill is BUY (long entry), second is SELL (exit)."""
        from trading_engine.domain.enums import Side

        df = _make_gap_fade_candles()
        engine = _make_engine({"TEST": df}, config=_test_cfg())
        report = engine.run()
        fills = report.fills
        assert fills[0].side == Side.BUY
        assert fills[1].side == Side.SELL

    def test_first_day_produces_no_fills(self):
        """On first day there is no prior close, so no trade can happen."""
        single_day = _make_gap_fade_candles().iloc[:1]
        engine = _make_engine({"TEST": single_day}, config=_test_cfg())
        report = engine.run()
        assert len(report.fills) == 0

    def test_report_has_metrics(self):
        df = _make_gap_fade_candles()
        engine = _make_engine({"TEST": df}, config=_test_cfg())
        report = engine.run()
        assert hasattr(report, "metrics")
        assert report.metrics is not None

    def test_no_zerodha_or_dotenv_in_strategy(self):
        source = (ROOT / "src" / "trading_engine" / "strategies" / "gap_fade.py").read_text()
        assert "zerodha" not in source.lower()
        assert "kite" not in source.lower()
        assert "load_dotenv" not in source
