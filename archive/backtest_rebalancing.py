"""Rebalancing Backtest — All 4 strategies, with vs without rebalancing.

Rebalancing rule:
  When a new signal fires and free_cash < MIN_CHUNK:
    - Find eligible open positions: unrealised gain < GAIN_GUARD (10%)
    - Skip Black Swan pairs (no single price to trim against)
    - Sell each eligible position down to the target equal-weight chunk
    - If freed cash >= MIN_CHUNK, open the new position
    - Otherwise reject the new signal

Compares All 4 combo baseline vs All 4 with rebalancing, side by side.
"""

from __future__ import annotations

import copy
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "archive"))
sys.path.insert(0, str(ROOT / "src"))

import simulate_combinations as sim
from trading_engine.strategy_priority import strategy_score

TOTAL_CAPITAL  = 2_00_000
MIN_CHUNK      = 50_000
GAIN_GUARD     = 0.10   # don't trim positions up more than this


# ── Price lookup helpers ──────────────────────────────────────────────────────

_price_index: dict[str, dict[str, float]] = {}   # symbol → {date_str → close}


def _build_price_index(symbol: str) -> None:
    if symbol in _price_index or "/" in symbol:
        return
    df = sim.fetch(symbol)
    if df is None:
        _price_index[symbol] = {}
        return
    _price_index[symbol] = {
        str(pd.Timestamp(d).date()): float(c)
        for d, c in zip(df["timestamp"].values, df["close"].values)
    }


def get_price(symbol: str, date_str: str, fallback: float) -> float:
    """Return close price for symbol on date_str, or fallback if unavailable."""
    if "/" in symbol:          # Black Swan pair — no single price
        return fallback
    idx = _price_index.get(symbol, {})
    if date_str in idx:
        return idx[date_str]
    # Walk back up to 5 trading days for weekends / holidays
    d = pd.Timestamp(date_str)
    for _ in range(5):
        d -= pd.Timedelta(days=1)
        ds = str(d.date())
        if ds in idx:
            return idx[ds]
    return fallback


# ── Core simulation ───────────────────────────────────────────────────────────

def run(all_trades: dict, rebalance: bool) -> dict:
    strategy_names = ["BB Squeeze", "MA Pullback", "Supertrend", "Black Swan"]

    relevant = []
    for sn in strategy_names:
        for t in all_trades.get(sn, []):
            relevant.append(copy.copy(t))

    valid = [t for t in relevant if t.get("entry_date") and t.get("exit_date")]
    valid.sort(key=lambda x: x["entry_date"])
    if not valid:
        return {}

    # Build date→entries map
    entries_by_date: dict[str, list[dict]] = defaultdict(list)
    for t in valid:
        entries_by_date[t["entry_date"]].append(t)

    # Build index of all dates to iterate (business days)
    start = pd.Timestamp(valid[0]["entry_date"])
    end   = pd.Timestamp(valid[-1]["exit_date"])
    all_dates = [str(d.date()) for d in pd.date_range(start, end, freq="B")]

    free_cash   = float(TOTAL_CAPITAL)
    active: list[dict] = []   # {trade, actual_qty, entry_price}
    yearly_pnl: dict[str, float] = defaultdict(float)
    total_pnl   = 0.0
    trades_taken    = 0
    trades_skipped  = 0
    rebal_events    = 0

    running_capital = float(TOTAL_CAPITAL)   # for % return calc

    for date_str in all_dates:

        # ── 1. Close exits today ─────────────────────────────────────────────
        still_open = []
        for slot in active:
            t = slot["trade"]
            if t["exit_date"] == date_str:
                pnl = (t["exit_price"] - slot["entry_price"]) * slot["actual_qty"]
                free_cash += slot["entry_price"] * slot["actual_qty"] + pnl
                yearly_pnl[date_str[:4]] += pnl
                total_pnl += pnl
            else:
                still_open.append(slot)
        active = still_open

        # ── 2. New signals today ─────────────────────────────────────────────
        signals = entries_by_date.get(date_str, [])
        if not signals:
            continue

        # Sort by priority (highest first)
        signals.sort(key=lambda t: strategy_score(t.get("strategy", "")), reverse=True)

        # Dedup by symbol — keep highest-priority strategy only
        seen_syms: set[str] = set()
        deduped = []
        for t in signals:
            sym = t.get("symbol", "")
            if sym not in seen_syms:
                seen_syms.add(sym)
                deduped.append(t)
        signals = deduped

        # Filter symbols already held
        held_syms = {slot["trade"].get("symbol", "") for slot in active}
        signals = [t for t in signals if t.get("symbol", "") not in held_syms]

        if not signals:
            continue

        # ── 3a. Enough free cash — normal allocation ─────────────────────────
        if free_cash >= MIN_CHUNK:
            max_slots = int(free_cash // MIN_CHUNK)
            selected = signals[:max_slots]
            trades_skipped += len(signals) - len(selected)
            chunk = free_cash / len(selected)
            for t in selected:
                qty = max(1, int(chunk / t["entry_price"]))
                free_cash -= qty * t["entry_price"]
                active.append({
                    "trade": t,
                    "actual_qty": qty,
                    "entry_price": t["entry_price"],
                })
                trades_taken += 1

        # ── 3b. Not enough cash — attempt rebalancing (if enabled) ───────────
        elif rebalance:
            n_new   = len(signals)
            n_total = len(active) + n_new
            target  = TOTAL_CAPITAL / n_total

            if target < MIN_CHUNK:
                # Too many positions — only take as many as MIN_CHUNK allows
                n_new = max(0, int(TOTAL_CAPITAL // MIN_CHUNK) - len(active))
                if n_new == 0:
                    trades_skipped += len(signals)
                    continue
                signals  = signals[:n_new]
                n_total  = len(active) + n_new
                target   = TOTAL_CAPITAL / n_total

            # Trim eligible open positions down to target
            freed = 0.0
            for slot in active:
                sym = slot["trade"].get("symbol", "")
                if "/" in sym:          # Black Swan pair — skip
                    continue
                cur_price = get_price(sym, date_str, slot["entry_price"])
                unrealised_pct = (cur_price - slot["entry_price"]) / slot["entry_price"]
                if unrealised_pct >= GAIN_GUARD:
                    continue            # protect winners

                cur_value = slot["actual_qty"] * slot["entry_price"]   # cost basis
                if cur_value <= target:
                    continue            # already at or below target, nothing to free

                sell_value = cur_value - target
                sell_qty   = int(sell_value / cur_price)
                if sell_qty < 1:
                    continue

                # Record partial exit P&L
                partial_pnl = (cur_price - slot["entry_price"]) * sell_qty
                yearly_pnl[date_str[:4]] += partial_pnl
                total_pnl += partial_pnl

                freed += sell_qty * cur_price
                slot["actual_qty"] -= sell_qty
                rebal_events += 1

            free_cash += freed

            if free_cash >= MIN_CHUNK:
                for t in signals:
                    qty = max(1, int(target / t["entry_price"]))
                    cost = qty * t["entry_price"]
                    if free_cash >= cost:
                        free_cash -= cost
                        active.append({
                            "trade": t,
                            "actual_qty": qty,
                            "entry_price": t["entry_price"],
                        })
                        trades_taken += 1
                    else:
                        trades_skipped += 1
            else:
                trades_skipped += len(signals)

        else:
            # No rebalancing — just skip
            trades_skipped += len(signals)

    return {
        "total_pnl":     round(total_pnl, 0),
        "yearly_pnl":    {k: round(v, 0) for k, v in yearly_pnl.items()},
        "trades_taken":  trades_taken,
        "trades_skipped": trades_skipped,
        "rebal_events":  rebal_events,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    all_trades = sim.collect_all_trades()

    # Pre-build price index for all non-pair symbols (needed for rebalancing guard)
    print("\nBuilding price index for rebalancing guard...")
    all_syms: set[str] = set()
    for trades in all_trades.values():
        for t in trades:
            sym = t.get("symbol", "")
            if "/" not in sym:
                all_syms.add(sym)
    for sym in sorted(all_syms):
        _build_price_index(sym)

    print("\nRunning baseline (no rebalancing)...")
    base = run(all_trades, rebalance=False)

    print("Running with rebalancing...")
    rebal = run(all_trades, rebalance=True)

    # ── Print results ─────────────────────────────────────────────────────────
    all_years = sorted(
        set(base["yearly_pnl"].keys()) | set(rebal["yearly_pnl"].keys())
    )

    col = 16
    header = f"{'Year':<6}{'Baseline':>{col}}{'Rebalancing':>{col}}{'Diff':>{col}}"
    sep = "─" * len(header)
    print(f"\n{sep}")
    print("ANNUAL RETURNS  (% of ₹2L starting capital, compounding)")
    print(sep)
    print(header)
    print("─" * len(header))

    running_b = running_r = float(TOTAL_CAPITAL)
    for year in all_years:
        b_pnl = base["yearly_pnl"].get(year, 0.0)
        r_pnl = rebal["yearly_pnl"].get(year, 0.0)
        b_pct = (b_pnl / running_b) * 100 if running_b > 0 else 0.0
        r_pct = (r_pnl / running_r) * 100 if running_r > 0 else 0.0
        running_b += b_pnl
        running_r += r_pnl
        diff = r_pct - b_pct
        sign_b = "+" if b_pct >= 0 else ""
        sign_r = "+" if r_pct >= 0 else ""
        sign_d = "+" if diff >= 0 else ""
        b_col = f"  {sign_b}{b_pct:.1f}%".rjust(col)
        r_col = f"  {sign_r}{r_pct:.1f}%".rjust(col)
        d_col = f"  {sign_d}{diff:.1f}%".rjust(col)
        print(f"{year:<6}{b_col}{r_col}{d_col}")

    print("─" * len(header))

    b_total_pct = (base["total_pnl"] / TOTAL_CAPITAL) * 100
    r_total_pct = (rebal["total_pnl"] / TOTAL_CAPITAL) * 100
    n_years     = max(1, len(all_years) - 1)  # exclude partial current year

    print(f"\n{'':6}{'Baseline':>{col}}{'Rebalancing':>{col}}")
    print(f"{'Total PnL':<20} ₹{base['total_pnl']:>10,.0f}   ₹{rebal['total_pnl']:>10,.0f}")
    print(f"{'CAGR (~)':<20} {b_total_pct/n_years:>9.1f}%   {r_total_pct/n_years:>9.1f}%")
    print(f"{'Trades taken':<20} {base['trades_taken']:>10}   {rebal['trades_taken']:>10}")
    print(f"{'Trades skipped':<20} {base['trades_skipped']:>10}   {rebal['trades_skipped']:>10}")
    print(f"{'Rebal events':<20} {'—':>10}   {rebal['rebal_events']:>10}")


if __name__ == "__main__":
    main()
