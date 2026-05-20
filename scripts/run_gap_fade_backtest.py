"""Run Gap Fade to VWAP / Prior Close backtest on locally stored Parquet candle data.

No broker API calls are made.  No live orders are placed.
Reads candle files from data/candles/NSE/{SYMBOL}/{interval}.parquet.

Usage:
    python3 scripts/run_gap_fade_backtest.py
    python3 scripts/run_gap_fade_backtest.py --symbols RELIANCE TCS
    python3 scripts/run_gap_fade_backtest.py --target-mode prior_close
    python3 scripts/run_gap_fade_backtest.py --long-only
    python3 scripts/run_gap_fade_backtest.py --output report.json
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from trading_engine.backtest.cost_model import CostModel  # noqa: E402
from trading_engine.backtest.data_feed import HistoricalDataFeed  # noqa: E402
from trading_engine.backtest.engine import BacktestEngine  # noqa: E402
from trading_engine.backtest.portfolio import BacktestPortfolio  # noqa: E402
from trading_engine.backtest.simulated_broker import SimulatedBroker  # noqa: E402
from trading_engine.backtest.slippage_model import SlippageModel  # noqa: E402
from trading_engine.strategies.gap_fade import GapFadeConfig, GapFadeStrategy  # noqa: E402

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_SYMBOLS = [
    "RELIANCE",
    "HDFCBANK",
    "INFY",
    "TCS",
    "ICICIBANK",
    "HDFC",
    "KOTAKBANK",
    "AXISBANK",
    "BAJFINANCE",
    "SBIN",
]
_DEFAULT_DATA_DIR = ROOT / "data"
_DEFAULT_INTERVAL = "minute"
_DEFAULT_INITIAL_CASH = Decimal("500000")
_DEFAULT_QUANTITY = 10
_DEFAULT_OUTPUT = ROOT / "reports" / "gap_fade_report.json"


def _build_config(args: argparse.Namespace) -> GapFadeConfig:
    return GapFadeConfig(
        strategy_id="gap_fade_v1",
        quantity=args.quantity,
        min_gap_bps=args.min_gap_bps,
        max_gap_bps=args.max_gap_bps,
        fade_trigger_bps=args.fade_trigger_bps,
        stop_loss_bps=args.stop_loss_bps,
        target_mode=args.target_mode,
        require_vwap_confirmation=not args.no_vwap_confirmation,
        allow_long_fades=not args.short_only,
        allow_short_fades=not args.long_only,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Gap Fade to VWAP / Prior Close backtest on local Parquet data."
    )
    parser.add_argument("--symbols", nargs="+", default=_DEFAULT_SYMBOLS)
    parser.add_argument("--data-dir", dest="data_dir", default=str(_DEFAULT_DATA_DIR))
    parser.add_argument("--interval", default=_DEFAULT_INTERVAL)
    parser.add_argument(
        "--initial-cash",
        dest="initial_cash",
        type=float,
        default=float(_DEFAULT_INITIAL_CASH),
    )
    parser.add_argument("--quantity", type=int, default=_DEFAULT_QUANTITY)
    parser.add_argument("--min-gap-bps", dest="min_gap_bps", type=float, default=60.0)
    parser.add_argument("--max-gap-bps", dest="max_gap_bps", type=float, default=300.0)
    parser.add_argument("--fade-trigger-bps", dest="fade_trigger_bps", type=float, default=20.0)
    parser.add_argument("--stop-loss-bps", dest="stop_loss_bps", type=float, default=80.0)
    parser.add_argument(
        "--target-mode",
        dest="target_mode",
        default="vwap",
        choices=["vwap", "prior_close", "half_gap"],
    )
    parser.add_argument(
        "--no-vwap-confirmation",
        dest="no_vwap_confirmation",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--long-only",
        dest="long_only",
        action="store_true",
        default=False,
        help="Only fade gap-downs (long trades)",
    )
    parser.add_argument(
        "--short-only",
        dest="short_only",
        action="store_true",
        default=False,
        help="Only fade gap-ups (short trades)",
    )
    parser.add_argument("--output", default=str(_DEFAULT_OUTPUT))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    data_dir = Path(args.data_dir)
    initial_cash = Decimal(str(args.initial_cash))
    output_path = Path(args.output)
    interval = args.interval

    print("\nGap Fade to VWAP / Prior Close Backtest")
    print(f"  Requested symbols:    {args.symbols}")
    print(f"  Data dir:             {data_dir}")
    print(f"  Interval:             {interval}")
    print(f"  Initial cash:         {initial_cash}")
    print(f"  Quantity:             {args.quantity}")
    print(f"  min_gap_bps:          {args.min_gap_bps}")
    print(f"  max_gap_bps:          {args.max_gap_bps}")
    print(f"  fade_trigger_bps:     {args.fade_trigger_bps}")
    print(f"  stop_loss_bps:        {args.stop_loss_bps}")
    print(f"  target_mode:          {args.target_mode}")
    print(f"  VWAP confirmation:    {not args.no_vwap_confirmation}")
    print(f"  long_only:            {args.long_only}")
    print(f"  short_only:           {args.short_only}")

    candles: dict[str, pd.DataFrame] = {}
    for symbol in args.symbols:
        path = data_dir / "candles" / "NSE" / symbol / f"{interval}.parquet"
        if not path.exists():
            print(f"  [skip] No data file for {symbol} at {path}")
            continue
        try:
            df = pd.read_parquet(path)
            candles[symbol] = df
            print(f"  Loaded {symbol}: {len(df)} bars")
        except Exception as exc:  # noqa: BLE001
            print(f"  [skip] Failed to read {symbol}: {exc}")

    if not candles:
        print("\nNo candle data found. Download historical data first, then re-run.\n")
        sys.exit(0)

    print(f"\nLoaded symbols: {list(candles.keys())}")

    config = _build_config(args)
    strategy = GapFadeStrategy(config=config)
    portfolio = BacktestPortfolio(initial_cash=initial_cash)
    cost_model = CostModel()
    slippage_model = SlippageModel(bps=Decimal("2"))
    broker = SimulatedBroker(portfolio, cost_model, slippage_model)
    feed = HistoricalDataFeed(candles, interval=interval)

    engine = BacktestEngine(
        strategy=strategy,
        data_feed=feed,
        portfolio=portfolio,
        simulated_broker=broker,
        initial_cash=initial_cash,
        strategy_id=config.strategy_id,
        symbols=list(candles.keys()),
        parameters={
            "interval": interval,
            "min_gap_bps": config.min_gap_bps,
            "max_gap_bps": config.max_gap_bps,
            "fade_trigger_bps": config.fade_trigger_bps,
            "stop_loss_bps": config.stop_loss_bps,
            "target_mode": config.target_mode,
        },
    )

    print(f"\nRunning backtest on {list(candles.keys())} ...")
    report = engine.run()

    m = report.metrics
    print(f"\n{'=' * 55}")
    print(f"Strategy : {report.strategy_id}")
    print(f"Period   : {report.start_time} -> {report.end_time}")
    print(f"Symbols  : {report.symbols}")
    print(f"Fills    : {len(report.fills)}")
    print(f"Equity   : {report.initial_cash} -> {report.final_equity}")
    print(f"Return   : {m.total_return:.4f}  ({m.total_pnl:+.2f} INR)")
    print(f"Max DD   : {m.max_drawdown:.4f}")
    print(f"Win rate : {m.win_rate:.4f}  ({m.winning_trades}W / {m.losing_trades}L)")
    print(f"Fees     : {m.total_fees:.2f}")
    print(f"{'=' * 55}\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    report.save_json(output_path)
    print(f"Report saved to {output_path}")


if __name__ == "__main__":
    main()
