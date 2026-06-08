"""Historical Backtest of the Master Risk Engine.

Reconstructs the last 5 years of PnL by running the 3 base strategies
with infinite capital, collecting ALL potential signals, and then
simulating the 2 Lakh capital constraint / dynamic sizing day-by-day.
"""

import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import run_paper_trader as pt_swan
import run_bb_squeeze_trader as pt_bb
import run_ma_pullback_trader as pt_ma

logging.basicConfig(level=logging.INFO, format="%(message)s")
_log = logging.getLogger(__name__)

TOTAL_ACCOUNT_CAPITAL = 2_00_000
MIN_CHUNK_SIZE = 50_000


def run_simulation():
    # 1. Temporarily bypass the "PAPER_TRADING_START" limit
    pt_swan.PAPER_TRADING_START = "2000-01-01"
    pt_bb.PAPER_TRADING_START = "2000-01-01"
    pt_ma.PAPER_TRADING_START = "2000-01-01"
    
    # Force 6 years of data to get full 5 years of signals (after 1y MA warmup)
    import yfinance as yf
    def forced_fetch(symbol: str) -> pd.DataFrame | None:
        try:
            df = yf.download(f"{symbol}.NS", period="6y", interval="1d", progress=False, auto_adjust=True)
            if df.empty: return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]
            df.index.name = "timestamp"
            df = df.reset_index()
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            return df.sort_values("timestamp").reset_index(drop=True).ffill().dropna(subset=["close"])
        except Exception:
            return None
            
    pt_swan.fetch = forced_fetch
    pt_bb.fetch_data = forced_fetch
    pt_ma.fetch_data = forced_fetch

    _log.info("Fetching infinite-capital trades for Swan...")
    swan_portfolio = pt_swan.load_portfolio()
    all_trades = []
    
    for pair in swan_portfolio:
        r = pt_swan.replay_pair(pair["symbol_a"], pair["symbol_b"], pair["optimal_params"])
        for t in r.get("closed_trades", []):
            t["strategy"] = "Black Swan"
            t["symbol"] = r["pair"]
            all_trades.append(t)

    _log.info("Fetching infinite-capital trades for BB Squeeze...")
    bb_portfolio = pt_bb.load_portfolio()
    for entry in bb_portfolio:
        sym = entry["symbol"]
        df = pt_bb.fetch_data(sym)
        if df is not None and len(df) >= pt_bb.BB_WINDOW + 2:
            st = pt_bb.replay_symbol(df, entry["best_params"])
            for t in st.get("closed_trades", []):
                t["strategy"] = "BB Squeeze"
                t["symbol"] = sym
                all_trades.append(t)

    _log.info("Fetching infinite-capital trades for MA Pullback...")
    ma_portfolio = pt_ma.load_portfolio()
    for entry in ma_portfolio:
        sym = entry["symbol"]
        df = pt_ma.fetch_data(sym)
        if df is not None and len(df) >= int(entry["optimal_params"]["trend_ma_period"]) + 2:
            st = pt_ma.replay_symbol(df, entry["optimal_params"])
            for t in st.get("closed_trades", []):
                t["strategy"] = "MA Pullback"
                t["symbol"] = sym
                all_trades.append(t)

    # 2. Sort all potential trades by their actual execution (entry) date
    # Some trades might lack entry_date if they failed, skip them.
    valid_trades = [t for t in all_trades if t.get("entry_date")]
    valid_trades.sort(key=lambda x: x["entry_date"])
    
    dates = sorted(list(set([t["entry_date"] for t in valid_trades] + [t["exit_date"] for t in valid_trades])))

    _log.info(f"Simulating Master Risk Engine from {dates[0]} to {dates[-1]}...")
    
    free_cash = TOTAL_ACCOUNT_CAPITAL
    active_portfolio = []  # List of trades currently held
    
    yearly_pnl = defaultdict(float)
    total_pnl = 0.0
    trades_taken = 0
    trades_skipped = 0

    for current_date in dates:
        # A. Exit any trades that close today
        still_open = []
        for trade in active_portfolio:
            if trade["exit_date"] == current_date:
                # Realize PnL based on ACTUAL dynamically allocated quantity
                actual_pnl = (trade["exit_price"] - trade["entry_price"]) * trade["actual_qty"]
                free_cash += (trade["entry_price"] * trade["actual_qty"]) + actual_pnl
                
                year = current_date[:4]
                yearly_pnl[year] += actual_pnl
                total_pnl += actual_pnl
            else:
                still_open.append(trade)
        active_portfolio = still_open

        # B. Handle new entry signals for today
        signals_today = [t for t in valid_trades if t["entry_date"] == current_date]
        if not signals_today:
            continue

        # Prioritize: MA > BB > Swan
        def strat_score(t):
            if t["strategy"] == "MA Pullback": return 3
            if t["strategy"] == "BB Squeeze": return 2
            return 1
            
        signals_today.sort(key=strat_score, reverse=True)

        if free_cash < MIN_CHUNK_SIZE:
            trades_skipped += len(signals_today)
            continue
            
        max_slots = int(free_cash // MIN_CHUNK_SIZE)
        selected = signals_today[:max_slots]
        trades_skipped += (len(signals_today) - len(selected))
        
        chunk_size = free_cash / len(selected)
        
        for t in selected:
            actual_qty = max(1, int(chunk_size / t["entry_price"]))
            t["actual_qty"] = actual_qty
            capital_locked = actual_qty * t["entry_price"]
            free_cash -= capital_locked
            active_portfolio.append(t)
            trades_taken += 1

    _log.info("\n=============================================")
    _log.info("MASTER RISK ENGINE (2 LAKH ACCOUNT CAP)")
    _log.info("=============================================")
    _log.info(f"Trades Taken  : {trades_taken}")
    _log.info(f"Trades Skipped: {trades_skipped} (Due to insufficient free cash)")
    _log.info(f"Total PnL     : ₹{total_pnl:,.0f}")
    _log.info("---------------------------------------------")
    
    for year in sorted(yearly_pnl.keys()):
        _log.info(f"  {year} PnL : ₹{yearly_pnl[year]:,.0f}")
    
    _log.info("=============================================")

if __name__ == "__main__":
    run_simulation()
