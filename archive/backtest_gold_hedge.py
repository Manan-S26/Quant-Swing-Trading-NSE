"""Gold ETF Hedge Backtest — All 4 strategies with GOLDBEES regime overlay.

Rule:
  When Nifty 50 closes BELOW its 200-day SMA → allocate one chunk to GOLDBEES.NS
  When Nifty 50 closes ABOVE its 200-day SMA → exit GOLDBEES position.

Entry/exit fills at next bar open (same convention as all other strategies).
GOLDBEES capital is carved from the free cash pool, reducing slots available
for other strategies while the hedge is active.

Compares: All 4 baseline  vs  All 4 + GOLDBEES hedge
"""

from __future__ import annotations

import copy
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "archive"))
sys.path.insert(0, str(ROOT / "src"))

import simulate_combinations as sim
import walk_forward_analysis as wf
from trading_engine.strategy_priority import strategy_score

TOTAL_CAPITAL = 2_00_000
MIN_CHUNK     = 40_000
SMA_PERIOD    = 200
GOLDBEES_CHUNK = 40_000   # capital reserved for the hedge slot


# ── Fetch helpers ─────────────────────────────────────────────────────────────

def fetch_nifty() -> pd.DataFrame:
    print("Fetching Nifty 50 (^NSEI)...")
    df = yf.download("^NSEI", period="12y", interval="1d", progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df.reset_index().rename(columns={"Date": "timestamp", "date": "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["sma200"] = df["close"].rolling(SMA_PERIOD).mean()
    df["bear_regime"] = df["close"] < df["sma200"]
    # regime for day D is determined by close of D, entry on open of D+1
    return df[["timestamp", "close", "sma200", "bear_regime"]].dropna()


def fetch_goldbees() -> pd.DataFrame:
    print("Fetching GOLDBEES.NS...")
    df = yf.download("GOLDBEES.NS", period="12y", interval="1d", progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df.reset_index().rename(columns={"Date": "timestamp", "date": "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df[["timestamp", "open", "close"]].dropna()


def build_regime_map(nifty: pd.DataFrame) -> dict[str, bool]:
    """date_str → True if bear regime on that date (Nifty < 200 SMA)."""
    return {
        str(row.timestamp.date()): bool(row.bear_regime)
        for row in nifty.itertuples()
    }


def build_price_map(df: pd.DataFrame, col: str) -> dict[str, float]:
    return {str(row.timestamp.date()): float(getattr(row, col)) for row in df.itertuples()}


# ── Core simulation ───────────────────────────────────────────────────────────

def run(all_trades: dict, use_hedge: bool,
        regime_map: dict, gold_open: dict, gold_close: dict) -> dict:

    strategy_names = ["BB Squeeze", "MA Pullback", "Supertrend", "Black Swan"]

    relevant = []
    for sn in strategy_names:
        for t in all_trades.get(sn, []):
            relevant.append(copy.copy(t))

    valid = [t for t in relevant if t.get("entry_date") and t.get("exit_date")]
    valid.sort(key=lambda x: x["entry_date"])

    entries_by_date: dict[str, list[dict]] = defaultdict(list)
    for t in valid:
        entries_by_date[t["entry_date"]].append(t)

    start = pd.Timestamp(valid[0]["entry_date"])
    end   = pd.Timestamp(valid[-1]["exit_date"])
    all_dates = [str(d.date()) for d in pd.date_range(start, end, freq="B")]

    free_cash  = float(TOTAL_CAPITAL)
    active: list[dict] = []       # strategy positions
    gold_slot: dict | None = None  # {qty, entry_price, entry_date}

    yearly_pnl: dict[str, float] = defaultdict(float)
    realized_equity = float(TOTAL_CAPITAL)
    peak_equity     = float(TOTAL_CAPITAL)
    max_dd_pct      = 0.0
    total_pnl       = 0.0
    trades_taken    = 0
    trades_skipped  = 0
    gold_trades     = 0

    prev_bear = False   # regime on previous day

    for date_str in all_dates:
        bear_today = regime_map.get(date_str, prev_bear)

        # ── 1. Close strategy exits ──────────────────────────────────────────
        still_open = []
        for slot in active:
            t = slot["trade"]
            if t["exit_date"] == date_str:
                pnl = (t["exit_price"] - slot["entry_price"]) * slot["actual_qty"]
                free_cash += slot["entry_price"] * slot["actual_qty"] + pnl
                yearly_pnl[date_str[:4]] += pnl
                total_pnl += pnl
                realized_equity += pnl
            else:
                still_open.append(slot)
        active = still_open

        # ── 2. GOLDBEES hedge logic ──────────────────────────────────────────
        if use_hedge:
            regime_flipped_bear = bear_today and not prev_bear
            regime_flipped_bull = (not bear_today) and prev_bear

            # Exit GOLDBEES when regime turns bull
            if regime_flipped_bull and gold_slot is not None:
                exit_price = gold_open.get(date_str) or gold_close.get(date_str, gold_slot["entry_price"])
                pnl = (exit_price - gold_slot["entry_price"]) * gold_slot["qty"]
                proceeds = gold_slot["entry_price"] * gold_slot["qty"] + pnl
                free_cash += proceeds
                yearly_pnl[date_str[:4]] += pnl
                total_pnl += pnl
                realized_equity += pnl
                gold_slot = None
                gold_trades += 1

            # Enter GOLDBEES when regime turns bear (if we have capital and no position)
            if regime_flipped_bear and gold_slot is None and free_cash >= GOLDBEES_CHUNK:
                entry_price = gold_open.get(date_str) or gold_close.get(date_str)
                if entry_price:
                    qty = max(1, int(GOLDBEES_CHUNK / entry_price))
                    cost = qty * entry_price
                    free_cash -= cost
                    gold_slot = {"qty": qty, "entry_price": entry_price, "entry_date": date_str}

        # ── 3. Strategy signals today ────────────────────────────────────────
        signals = entries_by_date.get(date_str, [])
        if signals:
            signals.sort(key=lambda t: strategy_score(t.get("strategy", "")), reverse=True)

            seen: set[str] = set()
            deduped = []
            for t in signals:
                sym = t.get("symbol", "")
                if sym not in seen:
                    seen.add(sym)
                    deduped.append(t)
            signals = deduped

            held = {slot["trade"].get("symbol", "") for slot in active}
            signals = [t for t in signals if t.get("symbol", "") not in held]

            if signals:
                max_slots = int(free_cash // MIN_CHUNK)
                if max_slots > 0:
                    selected = signals[:max_slots]
                    trades_skipped += len(signals) - len(selected)
                    chunk = free_cash / len(selected)
                    for t in selected:
                        qty = max(1, int(chunk / t["entry_price"]))
                        free_cash -= qty * t["entry_price"]
                        active.append({"trade": t, "actual_qty": qty, "entry_price": t["entry_price"]})
                        trades_taken += 1
                else:
                    trades_skipped += len(signals)

        # ── 4. Track drawdown on realized equity ─────────────────────────────
        if realized_equity > peak_equity:
            peak_equity = realized_equity
        dd = (peak_equity - realized_equity) / peak_equity if peak_equity > 0 else 0.0
        if dd > max_dd_pct:
            max_dd_pct = dd

        prev_bear = bear_today

    # Close any open GOLDBEES at end of period
    if use_hedge and gold_slot is not None:
        last_date = all_dates[-1]
        exit_price = gold_close.get(last_date, gold_slot["entry_price"])
        pnl = (exit_price - gold_slot["entry_price"]) * gold_slot["qty"]
        total_pnl += pnl
        gold_trades += 1

    # Build annual returns %
    running = float(TOTAL_CAPITAL)
    annual_returns = {}
    for yr in sorted(yearly_pnl):
        pnl_yr = yearly_pnl[yr]
        annual_returns[yr] = round((pnl_yr / running) * 100, 2)
        running += pnl_yr

    return {
        "total_pnl":      round(total_pnl, 0),
        "yearly_pnl":     {k: round(v, 0) for k, v in yearly_pnl.items()},
        "annual_returns": annual_returns,
        "trades_taken":   trades_taken,
        "trades_skipped": trades_skipped,
        "gold_trades":    gold_trades,
        "max_drawdown":   round(max_dd_pct * 100, 2),
        "final_value":    round(TOTAL_CAPITAL + total_pnl, 0),
    }


def risk_metrics(result: dict) -> dict:
    import statistics
    rets = list(result["annual_returns"].values())
    n = len(rets)
    if n < 2:
        return {"sharpe": 0.0, "calmar": 0.0, "cagr": 0.0, "max_dd": result["max_drawdown"]}
    mean_ret = statistics.mean(rets)
    std_ret  = statistics.stdev(rets)
    sharpe   = mean_ret / std_ret if std_ret > 0 else 0.0
    final    = result["final_value"]
    cagr     = ((final / TOTAL_CAPITAL) ** (1.0 / n) - 1.0) * 100 if final > 0 else 0.0
    calmar   = cagr / result["max_drawdown"] if result["max_drawdown"] > 0 else 0.0
    return {
        "sharpe": round(sharpe, 3),
        "calmar": round(calmar, 3),
        "cagr":   round(cagr, 2),
        "max_dd": result["max_drawdown"],
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    all_trades = sim.collect_all_trades()

    nifty    = fetch_nifty()
    goldbees = fetch_goldbees()

    regime_map = build_regime_map(nifty)
    gold_open  = build_price_map(goldbees, "open")
    gold_close = build_price_map(goldbees, "close")

    print("\nRunning baseline (All 4, no hedge)...")
    base  = run(all_trades, use_hedge=False, regime_map=regime_map,
                gold_open=gold_open, gold_close=gold_close)

    print("Running All 4 + GOLDBEES hedge...")
    hedge = run(all_trades, use_hedge=True, regime_map=regime_map,
                gold_open=gold_open, gold_close=gold_close)

    bm = risk_metrics(base)
    hm = risk_metrics(hedge)

    all_years = sorted(set(base["annual_returns"]) | set(hedge["annual_returns"]))

    col = 16
    header = f"{'Year':<6}{'Baseline':>{col}}{'+ Gold Hedge':>{col}}{'Diff':>{col}}"
    sep = "─" * len(header)
    print(f"\n{sep}")
    print("ANNUAL RETURNS  (% of capital at start of year, compounding)")
    print(sep)
    print(header)
    print("─" * len(header))

    for year in all_years:
        b = base["annual_returns"].get(year, 0.0)
        h = hedge["annual_returns"].get(year, 0.0)
        diff = h - b
        sb, sh, sd = ("+" if x >= 0 else "" for x in (b, h, diff))
        b_col    = f"  {sb}{b:.1f}%".rjust(col)
        h_col    = f"  {sh}{h:.1f}%".rjust(col)
        diff_col = f"  {sd}{diff:.1f}%".rjust(col)
        print(f"{year:<6}{b_col}{h_col}{diff_col}")

    print("─" * len(header))
    print(f"\n{'Metric':<18}{'Baseline':>{col}}{'+ Gold Hedge':>{col}}")
    print(f"{'CAGR':<18}{bm['cagr']:>{col-1}.1f}%{hm['cagr']:>{col-1}.1f}%")
    print(f"{'Sharpe':<18}{bm['sharpe']:>{col}.3f}{hm['sharpe']:>{col}.3f}")
    print(f"{'Max Drawdown':<18}{bm['max_dd']:>{col-1}.1f}%{hm['max_dd']:>{col-1}.1f}%")
    print(f"{'Calmar':<18}{bm['calmar']:>{col}.3f}{hm['calmar']:>{col}.3f}")
    print(f"{'Trades taken':<18}{base['trades_taken']:>{col}}{hedge['trades_taken']:>{col}}")
    print(f"{'Gold entries':<18}{'—':>{col}}{hedge['gold_trades']:>{col}}")

    neg_b = sum(1 for r in base["annual_returns"].values() if r < 0)
    neg_h = sum(1 for r in hedge["annual_returns"].values() if r < 0)
    print(f"{'Negative years':<18}{neg_b:>{col}}{neg_h:>{col}}")


if __name__ == "__main__":
    main()
