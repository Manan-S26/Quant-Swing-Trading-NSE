"""Walk-Forward Analysis + Risk Metrics for 4 Strategy Combinations.

Computes Sharpe, Calmar, and Max Drawdown for each combo over the full 10-year
period, then runs a walk-forward selection test:

  Walk-forward windows (expanding train, 1-year OOS):
    Train 2016–2020  → test 2021
    Train 2016–2021  → test 2022
    Train 2016–2022  → test 2023
    Train 2016–2023  → test 2024
    Train 2016–2024  → test 2025

  Selection criteria tested: Best Sharpe, Best Calmar, Best Total Return

Max drawdown is computed on the *realized* equity curve — equity is only updated
when a trade closes. This understates intra-trade drawdown but is accurate for
the portfolio-level capital question.
"""

from __future__ import annotations

import copy
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ARCHIVE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ARCHIVE_DIR))
from simulate_combinations import collect_all_trades, COMBOS, TOTAL_CAPITAL, MIN_CHUNK, STRAT_PRIORITY


# ============================================================
# Core simulation with equity-curve tracking
# ============================================================

def simulate_range(
    strategy_names: list[str],
    all_trades: dict,
    start_date: str | None = None,
    end_date: str | None = None,
    initial_capital: float = float(TOTAL_CAPITAL),
) -> dict:
    """
    Run the Master Risk Engine simulation on trades within [start_date, end_date].
    Returns yearly_pnl, annual_returns (%), total_pnl, max_drawdown (%), trades_taken.
    """
    relevant = []
    for sn in strategy_names:
        for t in all_trades.get(sn, []):
            ed = t.get("entry_date", "")
            if start_date and ed < start_date:
                continue
            if end_date and ed > end_date:
                continue
            relevant.append(copy.copy(t))

    valid = [t for t in relevant if t.get("entry_date") and t.get("exit_date")]
    valid.sort(key=lambda x: x["entry_date"])

    if not valid:
        return {
            "yearly_pnl": {}, "annual_returns": {}, "total_pnl": 0.0,
            "max_drawdown": 0.0, "trades_taken": 0, "final_value": initial_capital,
        }

    all_dates = sorted(
        set(t["entry_date"] for t in valid) | set(t["exit_date"] for t in valid)
    )

    free_cash = initial_capital
    active: list[dict] = []
    yearly_pnl: dict[str, float] = defaultdict(float)
    total_pnl = 0.0
    trades_taken = 0

    # Equity-curve tracking for drawdown
    realized_equity = initial_capital   # = initial + cumulative closed P&L
    peak_equity = initial_capital
    max_dd_pct = 0.0

    for current_date in all_dates:
        # A. Close exits
        still_open = []
        for slot in active:
            t, aq = slot["trade"], slot["actual_qty"]
            if t["exit_date"] == current_date:
                pnl = (t["exit_price"] - slot["entry_price"]) * aq
                free_cash += slot["entry_price"] * aq + pnl
                yr = current_date[:4]
                yearly_pnl[yr] += pnl
                total_pnl += pnl

                # Update realized equity curve
                realized_equity += pnl
                if realized_equity > peak_equity:
                    peak_equity = realized_equity
                dd = (peak_equity - realized_equity) / peak_equity if peak_equity > 0 else 0.0
                if dd > max_dd_pct:
                    max_dd_pct = dd
            else:
                still_open.append(slot)
        active = still_open

        # B. New entries
        signals = [t for t in valid if t["entry_date"] == current_date]
        if not signals:
            continue

        signals.sort(
            key=lambda t: STRAT_PRIORITY.get(t.get("strategy", ""), 0), reverse=True
        )

        if free_cash < MIN_CHUNK:
            continue

        max_slots = int(free_cash // MIN_CHUNK)
        selected = signals[:max_slots]
        chunk = free_cash / len(selected)

        for t in selected:
            aq = max(1, int(chunk / t["entry_price"]))
            free_cash -= aq * t["entry_price"]
            active.append({"trade": t, "actual_qty": aq, "entry_price": t["entry_price"]})
            trades_taken += 1

    # Annual returns (% on start-of-year equity, compounding)
    annual_returns: dict[str, float] = {}
    running = initial_capital
    for yr in sorted(yearly_pnl.keys()):
        pct = (yearly_pnl[yr] / running) * 100 if running > 0 else 0.0
        annual_returns[yr] = round(pct, 2)
        running += yearly_pnl[yr]

    return {
        "yearly_pnl": {k: round(v, 0) for k, v in yearly_pnl.items()},
        "annual_returns": annual_returns,
        "total_pnl": round(total_pnl, 0),
        "max_drawdown": round(max_dd_pct * 100, 2),   # expressed as %
        "trades_taken": trades_taken,
        "final_value": round(initial_capital + total_pnl, 0),
    }


def risk_metrics(result: dict, initial_capital: float = float(TOTAL_CAPITAL)) -> dict:
    """Compute Sharpe and Calmar from a simulate_range result."""
    rets = list(result["annual_returns"].values())
    n = len(rets)

    if n < 2:
        return {"sharpe": 0.0, "calmar": 0.0, "cagr": 0.0, "max_dd": result["max_drawdown"]}

    mean_ret = statistics.mean(rets)
    std_ret = statistics.stdev(rets)
    sharpe = mean_ret / std_ret if std_ret > 0 else 0.0

    final = result["final_value"]
    cagr = ((final / initial_capital) ** (1.0 / n) - 1.0) * 100 if final > 0 and n > 0 else 0.0

    calmar = cagr / result["max_drawdown"] if result["max_drawdown"] > 0 else 0.0

    return {
        "sharpe": round(sharpe, 3),
        "calmar": round(calmar, 3),
        "cagr": round(cagr, 2),
        "max_dd": result["max_drawdown"],
    }


# ============================================================
# Full 10-year risk metrics
# ============================================================

def print_full_metrics(all_trades: dict) -> dict[str, dict]:
    """Compute and print Sharpe, Calmar, Max DD for all combos over 10 years."""
    combo_results = {}
    for name, strategies in COMBOS.items():
        r = simulate_range(strategies, all_trades)
        m = risk_metrics(r)
        combo_results[name] = {"result": r, "metrics": m}

    names = list(COMBOS.keys())
    col_w = 16

    print(f"\n{'=' * 75}")
    print("  FULL 10-YEAR RISK METRICS  (2016 – 2025, excluding partial 2026)")
    print(f"{'=' * 75}")

    # Filter to 2016-2025 for metrics
    full_results_2016_2025 = {}
    for name, strategies in COMBOS.items():
        r = simulate_range(strategies, all_trades, start_date="2016-01-01", end_date="2025-12-31")
        m = risk_metrics(r)
        full_results_2016_2025[name] = {"result": r, "metrics": m}

    header = f"{'Metric':<18}" + "".join(f"{n:>{col_w}}" for n in names)
    print(header)
    print("-" * len(header))

    rows = [
        ("CAGR",        lambda m: f"{m['cagr']:+.1f}%"),
        ("Sharpe",      lambda m: f"{m['sharpe']:.3f}"),
        ("Max Drawdown",lambda m: f"{m['max_dd']:.1f}%"),
        ("Calmar",      lambda m: f"{m['calmar']:.3f}"),
    ]
    for label, fmt in rows:
        row = f"{label:<18}"
        for name in names:
            row += fmt(full_results_2016_2025[name]["metrics"]).rjust(col_w)
        print(row)

    print("-" * len(header))

    # Also print annual returns for reference
    all_years = sorted(set(
        yr for d in full_results_2016_2025.values()
        for yr in d["result"]["annual_returns"].keys()
    ))
    print(f"\n{'Year':<8}" + "".join(f"{n:>{col_w}}" for n in names))
    print("-" * (8 + col_w * len(names)))
    for yr in all_years:
        row = f"{yr:<8}"
        for name in names:
            v = full_results_2016_2025[name]["result"]["annual_returns"].get(yr, 0.0)
            sign = "+" if v >= 0 else ""
            row += f"{sign}{v:.1f}%".rjust(col_w)
        print(row)

    return full_results_2016_2025


# ============================================================
# Walk-forward selection test
# ============================================================

def walk_forward(all_trades: dict) -> None:
    """
    Expanding-window walk-forward:
      Train on 2016–(Y-1), pick best combo by each criterion.
      Measure actual OOS return in year Y.
    """
    TEST_YEARS = [2021, 2022, 2023, 2024, 2025]
    CRITERIA = ["sharpe", "calmar", "total_return"]
    names = list(COMBOS.keys())

    # Pre-compute full annual returns for each combo (used for OOS lookup)
    full_annual: dict[str, dict[str, float]] = {}
    for name, strategies in COMBOS.items():
        r = simulate_range(strategies, all_trades)
        full_annual[name] = r["annual_returns"]

    print(f"\n{'=' * 75}")
    print("  WALK-FORWARD SELECTION  (expanding train, 1-year OOS)")
    print(f"{'=' * 75}")

    for criterion in CRITERIA:
        print(f"\nSelection criterion: {criterion.upper()}")
        print(f"  {'Test yr':<9}{'Selected combo':<20}", end="")
        for n in names:
            print(f"{n[:12]:>14}", end="")
        print(f"  {'Winner':>12}")
        print("  " + "-" * (9 + 20 + 14 * len(names) + 14))

        wf_returns: list[float] = []

        for test_year in TEST_YEARS:
            train_end = f"{test_year - 1}-12-31"

            # Compute in-sample score for each combo
            scores: dict[str, float] = {}
            for name, strategies in COMBOS.items():
                r = simulate_range(strategies, all_trades,
                                   start_date="2016-01-01", end_date=train_end)
                if criterion == "total_return":
                    scores[name] = r["total_pnl"]
                else:
                    m = risk_metrics(r)
                    scores[name] = m[criterion]

            selected = max(scores, key=lambda n: scores[n])

            # OOS returns for every combo in test year
            oos: dict[str, float] = {
                n: full_annual[n].get(str(test_year), 0.0) for n in names
            }
            selected_return = oos[selected]
            winner = max(oos, key=lambda n: oos[n])
            wf_returns.append(selected_return)

            mark = " ✓" if selected == winner else "  "
            line = f"  {test_year:<9}{selected:<20}"
            for n in names:
                v = oos[n]
                sign = "+" if v >= 0 else ""
                cell = f"[{sign}{v:.1f}%]" if n == selected else f"{sign}{v:.1f}%"
                line += cell.rjust(14)
            line += f"  {winner:>12}{mark}"
            print(line)

        mean_wf = statistics.mean(wf_returns) if wf_returns else 0.0
        neg_count = sum(1 for r in wf_returns if r < 0)
        print(f"  {'WF mean OOS return:':<29}{mean_wf:+.1f}%   "
              f"(negative years: {neg_count}/{len(TEST_YEARS)})")

    # Benchmark: what if you just held the best full-10y combo in hindsight?
    print(f"\n  Hindsight benchmark (best full-10y combo selected):")
    best_hindsight = max(names, key=lambda n: sum(full_annual[n].values()))
    hindsight_oos = [full_annual[best_hindsight].get(str(y), 0.0) for y in TEST_YEARS]
    print(f"  Best in hindsight: {best_hindsight}")
    print(f"  OOS returns ({TEST_YEARS[0]}–{TEST_YEARS[-1]}): "
          + "  ".join(f"{r:+.1f}%" for r in hindsight_oos))
    print(f"  Mean: {statistics.mean(hindsight_oos):+.1f}%")


# ============================================================
# Main
# ============================================================

def main() -> None:
    all_trades = collect_all_trades()
    print_full_metrics(all_trades)
    walk_forward(all_trades)


if __name__ == "__main__":
    main()
