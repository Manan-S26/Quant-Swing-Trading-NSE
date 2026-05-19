"""Extended validation for selected First-Hour Momentum configs.

Runs two fixed configs (ICICIBANK RVOL=1.2, TCS no-RVOL) across monthly,
quarterly, train/test, and full-period windows with three slippage stress
scenarios.  No live trading.  No broker calls.  No .env.

Usage:
    python3 scripts/validate_selected_first_hour.py
    python3 scripts/validate_selected_first_hour.py --train-start 2025-01-01 --test-end 2026-01-31
"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
import time as time_mod
from datetime import date, time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import pandas as pd  # noqa: E402
from validate_first_hour_symbol_specific import (  # noqa: E402
    evaluate_task,
    filter_candles_by_date_range,
    filter_candles_by_rvol,
    load_all_candles,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DATA_DIR = ROOT / "data"
_DEFAULT_OUTPUT_DIR = ROOT / "reports"
_DEFAULT_INTERVAL = "minute"
_DEFAULT_INITIAL_CASH = Decimal("500000")
_DEFAULT_QUANTITY = 10

_BASE_PARAMS: dict = {
    "momentum_window_minutes": 15,
    "min_first_window_return_bps": 40.0,
    "latest_entry_time": time(10, 30),
    "stop_loss_bps": 60.0,
    "target_bps": None,
    "allow_shorts": False,
    "max_trades_per_symbol_per_day": 1,
}

SELECTED_CONFIGS: list[dict] = [
    {
        "label": "ICICIBANK_RVOL1.2",
        "symbol": "ICICIBANK",
        "params": _BASE_PARAMS,
        "min_first_window_rvol": 1.2,
    },
    {
        "label": "TCS_noRVOL",
        "symbol": "TCS",
        "params": _BASE_PARAMS,
        "min_first_window_rvol": None,
    },
]

# Slippage stress scenarios.  Each "tick" ≈ 1 extra bps for NSE large-caps
# at ~1000+ INR (conservative approximation; actual tick = 0.05 INR/share).
SLIPPAGE_SCENARIOS: list[tuple[str, Decimal]] = [
    ("base", Decimal("2")),
    ("+1tick", Decimal("3")),
    ("+2tick", Decimal("4")),
]

INSUFFICIENT_EVIDENCE_TRADES: int = 100  # fills (50 round-trips)
STRESS_MATERIAL_THRESHOLD: float = -500.0  # INR; any stress case below this = rejected


# ---------------------------------------------------------------------------
# Window builders
# ---------------------------------------------------------------------------


def build_month_windows(
    candles: dict[str, pd.DataFrame],
) -> list[tuple[str, date, date]]:
    """Return (label, start, end) for every calendar month present in data."""
    all_dates: set[date] = set()
    for df in candles.values():
        ts = df["timestamp"]
        if not pd.api.types.is_datetime64_any_dtype(ts):
            ts = pd.to_datetime(ts)
        all_dates.update(ts.dt.date.unique())

    if not all_dates:
        return []

    months: set[tuple[int, int]] = {(d.year, d.month) for d in all_dates}
    windows = []
    for year, month in sorted(months):
        last_day = calendar.monthrange(year, month)[1]
        start = date(year, month, 1)
        end = date(year, month, last_day)
        windows.append((f"{year}-{month:02d}", start, end))
    return windows


def build_quarter_windows(
    candles: dict[str, pd.DataFrame],
) -> list[tuple[str, date, date]]:
    """Return (label, start, end) for every calendar quarter present in data."""
    all_dates: set[date] = set()
    for df in candles.values():
        ts = df["timestamp"]
        if not pd.api.types.is_datetime64_any_dtype(ts):
            ts = pd.to_datetime(ts)
        all_dates.update(ts.dt.date.unique())

    if not all_dates:
        return []

    _q_start = {1: 1, 2: 4, 3: 7, 4: 10}
    _q_end = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}

    quarters: set[tuple[int, int]] = set()
    for d in all_dates:
        q = (d.month - 1) // 3 + 1
        quarters.add((d.year, q))

    windows = []
    for year, q in sorted(quarters):
        sm = _q_start[q]
        em, ed = _q_end[q]
        start = date(year, sm, 1)
        end = date(year, em, ed)
        windows.append((f"Q{q}-{year}", start, end))
    return windows


# ---------------------------------------------------------------------------
# Core slice runner
# ---------------------------------------------------------------------------


def run_config_on_slice(
    config_label: str,
    symbol: str,
    params: dict,
    min_rvol: float | None,
    candle_df: pd.DataFrame,
    start_date: date | None,
    end_date: date | None,
    slippage_label: str,
    slippage_bps: Decimal,
    window_label: str,
    window_type: str,
    initial_cash: Decimal,
    quantity: int,
    interval: str,
    rvol_lookback_days: int = 20,
) -> dict:
    """Run one config on one date slice with one slippage level. Returns result row."""
    sliced = filter_candles_by_date_range(candle_df, start_date, end_date)

    mwm = int(params.get("momentum_window_minutes", 15))
    if min_rvol is not None:
        sliced = filter_candles_by_rvol(sliced, min_rvol, mwm, rvol_lookback_days)

    _base_row = {
        "config_label": config_label,
        "symbol": symbol,
        "window_label": window_label,
        "window_type": window_type,
        "window_start": start_date,
        "window_end": end_date,
        "slippage_label": slippage_label,
        "slippage_bps": int(slippage_bps),
        "insufficient_evidence": False,
        "stress_rejected": False,
        "stress_reject_reason": None,
    }

    if sliced.empty:
        _base_row["error"] = "no_data"
        _base_row["total_pnl"] = None
        _base_row["gross_pnl"] = None
        _base_row["trade_count"] = None
        _base_row["win_rate"] = None
        _base_row["profit_factor"] = None
        _base_row["insufficient_evidence"] = True
        return _base_row

    metrics = evaluate_task(
        symbol,
        params,
        sliced,
        initial_cash,
        quantity,
        interval,
        slippage_bps=slippage_bps,
    )
    _base_row.update(metrics)
    return _base_row


# ---------------------------------------------------------------------------
# Rejection helpers
# ---------------------------------------------------------------------------


def check_insufficient_evidence(
    base_row: dict,
    min_trades: int = INSUFFICIENT_EVIDENCE_TRADES,
) -> bool:
    """Return True if the base scenario has fewer than min_trades fills."""
    tc = base_row.get("trade_count") or 0
    return tc < min_trades


def check_stress_rejection(
    stress_rows: list[dict],
    material_threshold: float = STRESS_MATERIAL_THRESHOLD,
) -> tuple[bool, str | None]:
    """Return (is_rejected, reason) if any stress case is materially negative."""
    for row in stress_rows:
        net = row.get("total_pnl")
        if net is not None and net < material_threshold:
            return True, f"{row['slippage_label']}_net={net:.0f}"
    return False, None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_extended_validation(
    configs: list[dict],
    candles: dict[str, pd.DataFrame],
    windows: list[tuple[str, str, date | None, date | None]],
    initial_cash: Decimal,
    quantity: int,
    interval: str,
    rvol_lookback_days: int = 20,
) -> list[dict]:
    """Run all configs × windows × slippage scenarios.

    windows: list of (window_label, window_type, start_date, end_date)
    Returns flat list of result dicts with evidence/stress flags stamped on each row.
    """
    results: list[dict] = []
    total_runs = len(configs) * len(windows) * len(SLIPPAGE_SCENARIOS)
    done = 0
    start_time = time_mod.time()

    print(
        f"\nRunning {len(configs)} configs × {len(windows)} windows "
        f"× {len(SLIPPAGE_SCENARIOS)} slippage = {total_runs} backtests (sequential)..."
    )

    for cfg in configs:
        sym = cfg["symbol"]
        if sym not in candles:
            print(f"  WARNING: {sym} not in candles — skipping config {cfg['label']}")
            continue
        candle_df = candles[sym]

        for window_label, window_type, start_date, end_date in windows:
            window_rows: list[dict] = []

            for slip_label, slip_bps in SLIPPAGE_SCENARIOS:
                row = run_config_on_slice(
                    config_label=cfg["label"],
                    symbol=sym,
                    params=cfg["params"],
                    min_rvol=cfg.get("min_first_window_rvol"),
                    candle_df=candle_df,
                    start_date=start_date,
                    end_date=end_date,
                    slippage_label=slip_label,
                    slippage_bps=slip_bps,
                    window_label=window_label,
                    window_type=window_type,
                    initial_cash=initial_cash,
                    quantity=quantity,
                    interval=interval,
                    rvol_lookback_days=rvol_lookback_days,
                )
                window_rows.append(row)
                done += 1
                _report_progress(done, total_runs, start_time)

            # Stamp evidence / stress flags on all rows in this window
            base_row = window_rows[0]
            insufficient = check_insufficient_evidence(base_row)
            if insufficient:
                stress_rejected, stress_reason = False, None
            else:
                stress_rejected, stress_reason = check_stress_rejection(window_rows[1:])

            for row in window_rows:
                row["insufficient_evidence"] = insufficient
                row["stress_rejected"] = stress_rejected
                row["stress_reject_reason"] = stress_reason
                results.append(row)

    print()
    return results


def _report_progress(done: int, total: int, start_time: float) -> None:
    elapsed = time_mod.time() - start_time
    avg = elapsed / done if done > 0 else 0
    rem = (total - done) * avg
    print(
        f"\r  Progress: {done}/{total} ({done / total:.1%}) | "
        f"Elapsed: {elapsed:.1f}s | Avg: {avg:.2f}s/t | ETA: {rem:.1f}s",
        end="",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Print / save
# ---------------------------------------------------------------------------


def print_extended_validation_results(results: list[dict]) -> None:
    """Print results grouped by window_type then config_label."""
    if not results:
        print("No results to display.")
        return

    def _n(v, fmt: str = ".1f") -> str:
        if v is None:
            return "None"
        try:
            return format(float(v), fmt)
        except (TypeError, ValueError):
            return str(v)

    def _flag(row: dict) -> str:
        if row.get("error") == "no_data":
            return "NO_DATA"
        if row.get("insufficient_evidence"):
            return "INSUFF"
        if row.get("stress_rejected"):
            return f"STRESS_FAIL({row.get('stress_reject_reason', '')})"
        return "OK"

    window_types = ["month", "quarter", "split", "full"]
    for wtype in window_types:
        type_rows = [r for r in results if r.get("window_type") == wtype]
        if not type_rows:
            continue

        print(f"\n{'=' * 70}")
        print(f"=== {wtype.upper()} WINDOWS ===")
        print(f"{'=' * 70}")

        config_labels = sorted({r["config_label"] for r in type_rows})
        for cfg_label in config_labels:
            print(f"\n  {cfg_label}:")
            cfg_rows = [r for r in type_rows if r["config_label"] == cfg_label]
            window_labels = sorted({r["window_label"] for r in cfg_rows})
            for wlabel in window_labels:
                w_rows = [r for r in cfg_rows if r["window_label"] == wlabel]
                base = next((r for r in w_rows if r["slippage_label"] == "base"), None)
                flag = _flag(base) if base else "?"
                parts = []
                for row in sorted(w_rows, key=lambda r: r.get("slippage_bps", 0)):
                    net = _n(row.get("total_pnl"))
                    sl = row.get("slippage_label", "?")
                    parts.append(f"{sl}={net}")
                tc = (base or {}).get("trade_count")
                print(f"    {wlabel:<12} tc={str(tc):<5} " + "  ".join(parts) + f"  [{flag}]")

    # Summary verdict per config
    print(f"\n{'=' * 70}")
    print("=== VERDICT SUMMARY ===")
    config_labels = sorted({r["config_label"] for r in results})
    for cfg_label in config_labels:
        cfg_rows = [r for r in results if r["config_label"] == cfg_label]
        full_rows = [
            r
            for r in cfg_rows
            if r.get("window_type") == "full" and r.get("slippage_label") == "base"
        ]
        if not full_rows:
            print(f"  {cfg_label}: no full-period base result")
            continue
        full = full_rows[0]
        net = full.get("total_pnl")
        tc = full.get("trade_count") or 0
        flag = _flag(full)
        print(f"  {cfg_label}: full_net={_n(net)}  trades={tc}  status={flag}")
        base_rows = [r for r in cfg_rows if r.get("slippage_label") == "base"]
        ok = sum(1 for r in base_rows if _flag(r) == "OK")
        total_w = len(base_rows)
        print(f"    Windows OK: {ok}/{total_w}")


def save_results(
    results: list[dict],
    output_dir: Path,
    prefix: str = "selected_first_hour_validation",
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{prefix}.csv"
    json_path = output_dir / f"{prefix}.json"

    pd.DataFrame(results).to_csv(csv_path, index=False)
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\nSaved {len(results)} rows to:")
    print(f"  {csv_path}")
    print(f"  {json_path}")
    return csv_path, json_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Extended validation for selected First-Hour Momentum configs."
    )
    parser.add_argument("--data-dir", default=str(_DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default=str(_DEFAULT_OUTPUT_DIR))
    parser.add_argument("--rvol-lookback-days", type=int, default=20)
    parser.add_argument("--train-start", type=date.fromisoformat, default=date(2025, 1, 1))
    parser.add_argument("--train-end", type=date.fromisoformat, default=date(2025, 9, 30))
    parser.add_argument("--test-start", type=date.fromisoformat, default=date(2025, 10, 1))
    parser.add_argument("--test-end", type=date.fromisoformat, default=date(2026, 1, 31))
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)

    symbols = list({cfg["symbol"] for cfg in SELECTED_CONFIGS})
    print(f"Loading candles for: {symbols}")
    candles = load_all_candles(symbols, data_dir, _DEFAULT_INTERVAL)
    if not candles:
        print("No candle data found. Exiting.")
        sys.exit(1)

    # Build all windows
    all_windows: list[tuple[str, str, date | None, date | None]] = []

    for label, start, end in build_month_windows(candles):
        all_windows.append((label, "month", start, end))

    for label, start, end in build_quarter_windows(candles):
        all_windows.append((label, "quarter", start, end))

    all_windows.append(("train", "split", args.train_start, args.train_end))
    all_windows.append(("test", "split", args.test_start, args.test_end))
    all_windows.append(("full", "full", None, None))

    print(f"\nWindow summary: {len(all_windows)} windows")
    print(f"  Months:   {sum(1 for w in all_windows if w[1] == 'month')}")
    print(f"  Quarters: {sum(1 for w in all_windows if w[1] == 'quarter')}")
    print(f"  Split:    {sum(1 for w in all_windows if w[1] == 'split')}")
    print(f"  Full:     {sum(1 for w in all_windows if w[1] == 'full')}")

    results = run_extended_validation(
        SELECTED_CONFIGS,
        candles,
        all_windows,
        _DEFAULT_INITIAL_CASH,
        _DEFAULT_QUANTITY,
        _DEFAULT_INTERVAL,
        rvol_lookback_days=args.rvol_lookback_days,
    )

    print_extended_validation_results(results)
    save_results(results, output_dir)


if __name__ == "__main__":
    main()
