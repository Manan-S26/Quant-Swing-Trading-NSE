"""Run ORB strategy in paper trading mode using local Parquet candle data.

Reads candle data from the local data directory (same layout as the historical
data pipeline), runs the ORB strategy through the paper trading engine, and
saves a paper trading report JSON.

No Zerodha API calls. No real order placement. No credentials required.
Exits cleanly if no local data exists.

Usage:
    python3 scripts/run_paper_orb.py

Output:
    paper_reports/paper_orb_report.json  (only if data exists)
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

# Ensure src/ is on the path when run directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trading_engine.backtest.cost_model import CostModel  # noqa: E402
from trading_engine.backtest.slippage_model import SlippageModel  # noqa: E402
from trading_engine.paper.broker import PaperExecutionBroker  # noqa: E402
from trading_engine.paper.engine import PaperTradingEngine  # noqa: E402
from trading_engine.paper.market_feed import PaperMarketFeed  # noqa: E402
from trading_engine.paper.portfolio import PaperPortfolio  # noqa: E402
from trading_engine.risk.engine import RiskEngine  # noqa: E402
from trading_engine.risk.limits import RiskLimits  # noqa: E402
from trading_engine.strategies.orb import OpeningRangeBreakoutStrategy, ORBConfig  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_DIR = ROOT / "data" / "candles" / "NSE"
REPORT_DIR = ROOT / "paper_reports"
INITIAL_CASH = Decimal("100000")
SYMBOLS = ["RELIANCE", "TCS", "INFY"]


def _find_parquet_files() -> dict[str, Path]:
    """Return {symbol: parquet_path} for available local Parquet files."""
    found: dict[str, Path] = {}
    for symbol in SYMBOLS:
        path = DATA_DIR / symbol / "1m.parquet"
        if path.exists():
            found[symbol] = path
    return found


def main() -> None:
    parquet_files = _find_parquet_files()

    if not parquet_files:
        print(
            f"No local Parquet data found in {DATA_DIR}.\n"
            "Run the historical data downloader first (Milestone 4).\n"
            "Exiting cleanly — no report generated."
        )
        sys.exit(0)

    print(f"Found data for: {list(parquet_files.keys())}")

    import pandas as pd  # deferred — only needed when data exists

    candles: dict[str, pd.DataFrame] = {}
    for symbol, path in parquet_files.items():
        df = pd.read_parquet(path)
        print(f"  {symbol}: {len(df)} bars")
        candles[symbol] = df

    # --- Strategy ---
    config = ORBConfig(
        opening_range_minutes=15,
        quantity=1,
    )
    strategy = OpeningRangeBreakoutStrategy(config=config)

    # --- Market feed ---
    feed = PaperMarketFeed(candles)

    # --- Portfolio ---
    portfolio = PaperPortfolio(initial_cash=INITIAL_CASH)

    # --- Costs ---
    cost = CostModel()
    slippage = SlippageModel(bps=Decimal("2"))

    # --- Execution broker ---
    broker = PaperExecutionBroker(portfolio, cost, slippage)

    # --- Risk engine ---
    risk_engine = RiskEngine(
        limits=RiskLimits(
            max_daily_loss=Decimal("2000"),
            max_order_value=Decimal("50000"),
            max_open_positions=5,
            max_trades_per_day=20,
            max_orders_per_second=2,
        )
    )

    # --- Engine ---
    engine = PaperTradingEngine(
        strategy=strategy,
        market_feed=feed,
        portfolio=portfolio,
        execution_broker=broker,
        risk_engine=risk_engine,
        strategy_id=config.strategy_id,
        symbols=list(candles.keys()),
        initial_cash=INITIAL_CASH,
        parameters={"mode": "paper", "source": "local_parquet"},
    )

    print("\nRunning paper trading engine...")
    report = engine.run()

    print("\nPaper trading complete:")
    print(f"  Fills:     {len(report.fills)}")
    print(f"  Rejected:  {len(report.rejected_risk_decisions)}")
    print(f"  Initial:   {report.initial_cash}")
    print(f"  Final:     {report.final_equity}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / "paper_orb_report.json"
    report.save_json(out_path)
    print(f"\nReport saved: {out_path}")


if __name__ == "__main__":
    main()
