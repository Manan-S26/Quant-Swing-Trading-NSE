"""Example script: run ORB backtest on locally stored Parquet candle data.

Usage:
    python3 scripts/run_orb_backtest.py

Requirements:
  - Candle data must be downloaded first via HistoricalDataDownloader.
  - Expected layout: data/candles/NSE/{SYMBOL}/minute.parquet
  - No Zerodha calls are made.
  - If no candle files are found the script exits with a clear message.

Output:
  - Prints a summary to stdout.
  - Saves a JSON report to reports/orb_backtest_report.json.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402 — after sys.path patch

from trading_engine.backtest.cost_model import CostModel  # noqa: E402
from trading_engine.backtest.data_feed import HistoricalDataFeed  # noqa: E402
from trading_engine.backtest.engine import BacktestEngine  # noqa: E402
from trading_engine.backtest.portfolio import BacktestPortfolio  # noqa: E402
from trading_engine.backtest.simulated_broker import SimulatedBroker  # noqa: E402
from trading_engine.backtest.slippage_model import SlippageModel  # noqa: E402
from trading_engine.strategies.orb import OpeningRangeBreakoutStrategy, ORBConfig  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration — edit these to match your local data.
# ---------------------------------------------------------------------------

SYMBOLS = ["RELIANCE", "HDFCBANK", "INFY", "TCS", "ICICIBANK"]
DATA_DIR = ROOT / "data"
INTERVAL = "minute"
INITIAL_CASH = Decimal("500000")
REPORT_PATH = ROOT / "reports" / "orb_backtest_report.json"

ORB_CONFIG = ORBConfig(
    strategy_id="orb_v1",
    opening_range_minutes=15,
    quantity=10,
    target_r_multiple=Decimal("2"),
    stop_buffer_bps=Decimal("5"),
    entry_buffer_bps=Decimal("5"),
)


def main() -> None:
    candles: dict[str, pd.DataFrame] = {}

    for symbol in SYMBOLS:
        path = DATA_DIR / "candles" / "NSE" / symbol / f"{INTERVAL}.parquet"
        if path.exists():
            df = pd.read_parquet(path)
            candles[symbol] = df
            print(f"  Loaded {symbol}: {len(df)} bars")
        else:
            print(f"  [skip] No data for {symbol} at {path}")

    if not candles:
        print(
            "\nNo candle data found under data/candles/NSE/.\n"
            "Download historical data first using HistoricalDataDownloader.\n"
            "Example:\n"
            "  from trading_engine.data.historical import HistoricalDataDownloader\n"
            "  downloader = HistoricalDataDownloader(broker=zerodha_broker, data_dir='data/')\n"
            "  downloader.download_universe(instruments, universe, 'minute', from_date, to_date)\n"
        )
        sys.exit(0)

    print(f"\nRunning ORB backtest on {list(candles.keys())} ...")

    strategy = OpeningRangeBreakoutStrategy(config=ORB_CONFIG)
    portfolio = BacktestPortfolio(initial_cash=INITIAL_CASH)
    cost_model = CostModel()
    slippage_model = SlippageModel(bps=Decimal("2"))
    broker = SimulatedBroker(portfolio, cost_model, slippage_model)
    feed = HistoricalDataFeed(candles, interval=INTERVAL)

    engine = BacktestEngine(
        strategy=strategy,
        data_feed=feed,
        portfolio=portfolio,
        simulated_broker=broker,
        initial_cash=INITIAL_CASH,
        strategy_id=ORB_CONFIG.strategy_id,
        symbols=list(candles.keys()),
        parameters={
            "interval": INTERVAL,
            "opening_range_minutes": ORB_CONFIG.opening_range_minutes,
        },
    )

    report = engine.run()

    print(f"\n{'=' * 50}")
    print(f"Strategy : {report.strategy_id}")
    print(f"Period   : {report.start_time} → {report.end_time}")
    print(f"Fills    : {len(report.fills)}")
    print(f"Equity   : {report.initial_cash} → {report.final_equity}")
    m = report.metrics
    print(f"Return   : {m.total_return:.4f}  ({m.total_pnl:+.2f} INR)")
    print(f"Max DD   : {m.max_drawdown:.4f}")
    print(f"Win rate : {m.win_rate:.4f}  ({m.winning_trades}W / {m.losing_trades}L)")
    print(f"Fees     : {m.total_fees:.2f}")
    print(f"{'=' * 50}\n")

    report.save_json(REPORT_PATH)
    print(f"Report saved to {REPORT_PATH}")


if __name__ == "__main__":
    main()
