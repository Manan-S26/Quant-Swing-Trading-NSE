"""Parallelized First-Hour Momentum symbol-specific validation.

Evaluates parameter combinations across symbols in parallel, saving results to CSV/JSON.
Uses local Parquet data only. No live trading or broker calls.

Usage:
    python3 scripts/validate_first_hour_symbol_specific.py --workers 4
    python3 scripts/validate_first_hour_symbol_specific.py --fast
    python3 scripts/validate_first_hour_symbol_specific.py --sample-months 2025-01 2025-06
    python3 scripts/validate_first_hour_symbol_specific.py --fast-filter-search
    python3 scripts/validate_first_hour_symbol_specific.py --fast-filter-search --max-combinations-per-symbol 48
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time as time_mod
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, time
from decimal import Decimal
from itertools import product
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
from trading_engine.strategies.first_hour_momentum import (  # noqa: E402
    FirstHourMomentumConfig,
    FirstHourMomentumStrategy,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_ALL_SYMBOLS = [
    "RELIANCE",
    "HDFCBANK",
    "ICICIBANK",
    "INFY",
    "TCS",
    "LT",
    "SBIN",
    "AXISBANK",
    "BHARTIARTL",
    "ITC",
]
_FAST_SYMBOLS = ["TCS", "INFY", "ICICIBANK"]
_DEFAULT_DATA_DIR = ROOT / "data"
_DEFAULT_INTERVAL = "minute"
_DEFAULT_INITIAL_CASH = Decimal("500000")
_DEFAULT_QUANTITY = 10
_DEFAULT_OUTPUT_DIR = ROOT / "reports"

PARAM_GRID: dict[str, list] = {
    "momentum_window_minutes": [15, 30, 60],
    "min_first_window_return_bps": [40, 60, 80, 120],
    "latest_entry_time": [time(10, 30), time(11, 30), time(12, 0)],
    "stop_loss_bps": [60, 80, 120],
    "target_bps": [None, 120, 200],
    "allow_shorts": [False],
    "max_trades_per_symbol_per_day": [1],
}

# Fixed base params for fast-filter-search mode (best config found so far).
FILTER_SEARCH_BASE_PARAMS: dict = {
    "momentum_window_minutes": 15,
    "min_first_window_return_bps": 40.0,
    "latest_entry_time": time(10, 30),
    "stop_loss_bps": 60.0,
    "target_bps": None,
    "allow_shorts": False,
    "max_trades_per_symbol_per_day": 1,
}

# Only these filter params are swept in fast-filter-search mode (4*4*3 = 48 combos).
FILTER_SEARCH_GRID: dict[str, list] = {
    "min_first_window_abs_move": [None, 1.0, 2.0, 3.0],
    "min_opening_range_abs": [None, 2.0, 4.0, 6.0],
    "min_first_window_rvol": [None, 1.2, 1.5],
}

# Baseline per-symbol metrics from best config (momentum_window=15, return=40bps, sl=60bps).
_FAST_FILTER_BASELINE: dict[str, dict] = {
    "ICICIBANK": {
        "total_pnl": -2269,
        "gross_pnl": 336,
        "total_fees": 2605,
        "profit_factor": 1.17,
        "trade_count": 100,
    },
    "TCS": {
        "total_pnl": -2315,
        "gross_pnl": 663,
        "total_fees": 2979,
        "profit_factor": 1.13,
        "trade_count": 100,
    },
    "INFY": {
        "total_pnl": -3800,
        "gross_pnl": 94,
        "total_fees": 3874,
        "profit_factor": 1.02,
        "trade_count": 146,
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _params_to_row(params: dict) -> dict:
    row = {}
    for k, v in params.items():
        if isinstance(v, time):
            row[k] = str(v)
        elif v is None:
            row[k] = None
        else:
            row[k] = v
    return row


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _trade_level_metrics(fills: list) -> dict:
    from trading_engine.domain.enums import Side  # noqa: PLC0415

    buy_queue: dict[str, list[tuple[int, Decimal]]] = {}
    gross_pnls: list[Decimal] = []

    for fill in fills:
        sym = fill.symbol
        if fill.side == Side.BUY:
            buy_queue.setdefault(sym, []).append((fill.quantity, fill.price))
        elif fill.side == Side.SELL:
            entries = buy_queue.get(sym, [])
            remaining = fill.quantity
            cost = Decimal("0")
            new_entries = []
            for qty, price in entries:
                if remaining <= 0:
                    new_entries.append((qty, price))
                    continue
                used = min(qty, remaining)
                cost += Decimal(str(used)) * price
                remaining -= used
                leftover = qty - used
                if leftover > 0:
                    new_entries.append((leftover, price))
            buy_queue[sym] = new_entries
            gross_pnls.append(Decimal(str(fill.quantity)) * fill.price - cost)

    n = len(gross_pnls)
    if n == 0:
        return {
            "round_trips": 0,
            "gross_pnl": None,
            "profit_factor": None,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": None,
            "average_gross_pnl": None,
        }

    wins = [p for p in gross_pnls if p > 0]
    losses = [p for p in gross_pnls if p < 0]
    total_gross = sum(gross_pnls, Decimal("0"))

    pf = None
    if losses:
        gross_loss = abs(sum(losses, Decimal("0")))
        if gross_loss > 0:
            pf = _safe_float(sum(wins, Decimal("0")) / gross_loss)

    return {
        "round_trips": n,
        "gross_pnl": _safe_float(total_gross),
        "profit_factor": pf,
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": _safe_float(Decimal(str(len(wins))) / Decimal(str(n))),
        "average_gross_pnl": _safe_float(total_gross / Decimal(str(n))),
    }


def _derive_config_times(momentum_window_minutes: int, latest_entry_time: time) -> tuple[time, int]:
    session_minutes = 9 * 60 + 15 + momentum_window_minutes
    earliest_entry = time(session_minutes // 60, session_minutes % 60)
    return earliest_entry, momentum_window_minutes


def _compute_rejection(
    test_trade_count: int | None,
    test_net_pnl: float | None,
    train_net_pnl: float | None,
) -> str | None:
    """Return rejection reason string, or None if the combo passes all rules.

    Rules checked in order:
    1. test_trade_count < 20  — insufficient test data.
    2. train_net_pnl > 0 and test_net_pnl <= 0  — overfitting signal (train+/test-).
    3. test_net_pnl <= 0  — not profitable in test period.
    """
    tc = test_trade_count or 0
    if tc < 20:
        return f"test_trades={tc}<20"
    test_neg = test_net_pnl is not None and test_net_pnl <= 0
    train_pos = train_net_pnl is not None and train_net_pnl > 0
    if test_neg and train_pos:
        return "train_pos_test_neg"
    if test_neg:
        return "test_net<=0"
    return None


# ---------------------------------------------------------------------------
# Date range filtering
# ---------------------------------------------------------------------------


def filter_candles_by_date_range(
    candle_df: pd.DataFrame,
    start_date: date | None,
    end_date: date | None,
) -> pd.DataFrame:
    """Return candles where date is in [start_date, end_date] (inclusive).

    If both bounds are None, returns candle_df unchanged.
    """
    if start_date is None and end_date is None:
        return candle_df

    df = candle_df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"])

    d = df["timestamp"].dt.date
    mask = pd.Series(True, index=df.index)
    if start_date is not None:
        mask &= d >= start_date
    if end_date is not None:
        mask &= d <= end_date
    return df[mask].reset_index(drop=True)


# ---------------------------------------------------------------------------
# RVOL helpers (research-layer pre-filter, not injected into strategy)
# ---------------------------------------------------------------------------


def compute_rvol_eligible_dates(
    candle_df: pd.DataFrame,
    window_minutes: int,
    min_rvol: float,
    lookback_days: int = 20,
) -> set:
    """Return dates where first-window RVOL >= min_rvol.

    RVOL = current day first-window volume / rolling mean of prior N days.
    Dates with < lookback_days prior history pass automatically (filter is
    skipped for those days, not applied pessimistically — no crash).
    """
    df = candle_df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"])

    session_start_min = 9 * 60 + 15  # 09:15
    df["_time_min"] = df["timestamp"].dt.hour * 60 + df["timestamp"].dt.minute
    df["_date"] = df["timestamp"].dt.date

    fw_mask = (df["_time_min"] >= session_start_min) & (
        df["_time_min"] < session_start_min + window_minutes
    )
    daily_vol = df[fw_mask].groupby("_date")["volume"].sum().sort_index()

    if daily_vol.empty:
        return set()

    dates = daily_vol.index.tolist()
    eligible: set = set()
    for i, d in enumerate(dates):
        if i < lookback_days:
            # Insufficient history — skip filter, always eligible.
            eligible.add(d)
            continue
        rolling_avg = float(daily_vol.iloc[i - lookback_days : i].mean())
        if rolling_avg == 0:
            # Cannot compute RVOL — skip filter, always eligible.
            eligible.add(d)
            continue
        rvol = float(daily_vol.iloc[i]) / rolling_avg
        if rvol >= min_rvol:
            eligible.add(d)

    return eligible


def filter_candles_by_rvol(
    symbol_candles: pd.DataFrame,
    min_rvol: float | None,
    window_minutes: int,
    lookback_days: int = 20,
) -> pd.DataFrame:
    """Filter candle DataFrame to dates that pass the RVOL threshold.

    Returns candles unchanged when min_rvol is None.
    Dates with insufficient history pass automatically.
    """
    if min_rvol is None:
        return symbol_candles

    eligible_dates = compute_rvol_eligible_dates(
        symbol_candles, window_minutes, min_rvol, lookback_days
    )

    df = symbol_candles.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"])

    df["_date"] = df["timestamp"].dt.date
    filtered = df[df["_date"].isin(eligible_dates)].drop(columns=["_date"])
    return filtered.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Core Task Logic
# ---------------------------------------------------------------------------


def evaluate_task(
    symbol: str,
    params: dict,
    symbol_candles: pd.DataFrame,
    initial_cash: Decimal,
    quantity: int,
    interval: str,
    slippage_bps: Decimal = Decimal("2"),
) -> dict:
    """Run backtest for ONE symbol and ONE config."""
    mwm = int(params.get("momentum_window_minutes", 30))
    latest_entry = params.get("latest_entry_time", time(12, 0))
    earliest_entry, min_bars = _derive_config_times(mwm, latest_entry)

    try:
        cfg = FirstHourMomentumConfig(
            strategy_id=f"fhm_val_{symbol}",
            quantity=quantity,
            momentum_window_minutes=mwm,
            earliest_entry_time=earliest_entry,
            latest_entry_time=latest_entry,
            min_bars_before_signal=min_bars,
            min_first_window_return_bps=float(params.get("min_first_window_return_bps", 60.0)),
            stop_loss_bps=float(params.get("stop_loss_bps", 80.0)),
            target_bps=(
                float(params["target_bps"]) if params.get("target_bps") is not None else None
            ),
            allow_shorts=bool(params.get("allow_shorts", False)),
            max_trades_per_symbol_per_day=int(params.get("max_trades_per_symbol_per_day", 1)),
            min_first_window_abs_move=(
                float(params["min_first_window_abs_move"])
                if params.get("min_first_window_abs_move") is not None
                else None
            ),
            min_opening_range_abs=(
                float(params["min_opening_range_abs"])
                if params.get("min_opening_range_abs") is not None
                else None
            ),
            # min_first_window_rvol is handled as a pre-filter on candles, not in the strategy.
        )
    except Exception as exc:
        res = _params_to_row(params)
        res.update({"symbol": symbol, "error": str(exc)})
        return res

    strategy = FirstHourMomentumStrategy(config=cfg)
    portfolio = BacktestPortfolio(initial_cash=initial_cash)
    broker = SimulatedBroker(portfolio, CostModel(), SlippageModel(bps=slippage_bps))
    feed = HistoricalDataFeed({symbol: symbol_candles}, interval=interval)
    engine = BacktestEngine(
        strategy=strategy,
        data_feed=feed,
        portfolio=portfolio,
        simulated_broker=broker,
        initial_cash=initial_cash,
        strategy_id=cfg.strategy_id,
        symbols=[symbol],
    )

    report = engine.run()
    m = report.metrics
    tl = _trade_level_metrics(report.fills)

    net_pnl = m.total_pnl
    total_fees_val = m.total_fees
    gross_pnl_formula = _safe_float(net_pnl + total_fees_val)
    net_pnl_float = _safe_float(net_pnl)

    n_trips = tl["round_trips"]
    avg_gross_pnl: float | None = None
    fees_per_trade: float | None = None
    gross_pnl_per_trade: float | None = None
    fee_drag_ratio: float | None = None

    if n_trips > 0:
        if tl["gross_pnl"] is not None:
            avg_gross_pnl = tl["gross_pnl"] / n_trips
            gross_pnl_per_trade = avg_gross_pnl
        fees_per_trade = _safe_float(total_fees_val / Decimal(str(n_trips)))

    if gross_pnl_formula is not None and gross_pnl_formula != 0:
        fee_drag_ratio = _safe_float(float(total_fees_val) / abs(gross_pnl_formula))

    gross_positive_net_negative = bool(
        gross_pnl_formula is not None
        and gross_pnl_formula > 0
        and net_pnl_float is not None
        and net_pnl_float < 0
    )

    avg_trade_pnl = None
    if n_trips > 0:
        avg_trade_pnl = _safe_float(net_pnl / Decimal(str(n_trips)))

    row = _params_to_row(params)
    row.update(
        {
            "symbol": symbol,
            "error": None,
            "total_pnl": net_pnl_float,
            "gross_pnl": gross_pnl_formula,
            "total_fees": _safe_float(total_fees_val),
            "trade_count": m.trade_count,
            "win_rate": tl["win_rate"],
            "profit_factor": tl["profit_factor"],
            "average_trade_pnl": avg_trade_pnl,
            "avg_gross_pnl": avg_gross_pnl,
            "fees_per_trade": fees_per_trade,
            "gross_pnl_per_trade": gross_pnl_per_trade,
            "fee_drag_ratio": fee_drag_ratio,
            "gross_positive_net_negative": gross_positive_net_negative,
            "max_drawdown": _safe_float(m.max_drawdown),
        }
    )
    return row


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def build_tasks(
    symbols: list[str],
    grid: dict[str, list],
    max_combos: int | None = None,
) -> list[tuple[str, dict]]:
    keys = list(grid.keys())
    combos = [dict(zip(keys, c, strict=True)) for c in product(*grid.values())]
    if max_combos and max_combos < len(combos):
        combos = combos[:max_combos]

    tasks = []
    for sym in symbols:
        for combo in combos:
            tasks.append((sym, combo))
    return tasks


def build_filter_search_tasks(
    symbols: list[str],
    max_combos_per_symbol: int | None = None,
) -> list[tuple[str, dict]]:
    """Build tasks for fast-filter-search mode.

    Base params are fixed to FILTER_SEARCH_BASE_PARAMS.
    Only filter params in FILTER_SEARCH_GRID are swept.
    """
    keys = list(FILTER_SEARCH_GRID.keys())
    combos = [dict(zip(keys, c, strict=True)) for c in product(*FILTER_SEARCH_GRID.values())]
    if max_combos_per_symbol and max_combos_per_symbol < len(combos):
        combos = combos[:max_combos_per_symbol]

    tasks = []
    for sym in symbols:
        for combo in combos:
            params = {**FILTER_SEARCH_BASE_PARAMS, **combo}
            tasks.append((sym, params))
    return tasks


def filter_candles(candles: dict[str, pd.DataFrame], months: list[str]) -> dict[str, pd.DataFrame]:
    """Filter bars to only those matching YYYY-MM strings."""
    if not months:
        return candles

    filtered = {}
    for sym, df in candles.items():
        # Ensure timestamp is datetime
        if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
            df["timestamp"] = pd.to_datetime(df["timestamp"])

        mask = df["timestamp"].dt.strftime("%Y-%m").isin(months)
        filtered_df = df[mask].copy()
        if not filtered_df.empty:
            filtered[sym] = filtered_df
            print(f"  {sym}: filtered to {len(filtered_df)} bars ({months})")
        else:
            print(f"  {sym}: NO BARS MATCHED {months}")
    return filtered


def load_all_candles(symbols: list[str], data_dir: Path, interval: str) -> dict[str, pd.DataFrame]:
    candles = {}
    for sym in symbols:
        path = data_dir / "candles" / "NSE" / sym / f"{interval}.parquet"
        if path.exists():
            try:
                candles[sym] = pd.read_parquet(path)
                print(f"  Loaded {sym}: {len(candles[sym])} bars")
            except Exception as exc:
                print(f"  Failed to load {sym}: {exc}")
    return candles


def run_parallel(
    tasks: list[tuple[str, dict]],
    candles: dict[str, pd.DataFrame],
    workers: int,
    initial_cash: Decimal,
    quantity: int,
    interval: str,
) -> list[dict]:
    results = []
    total = len(tasks)
    start_time = time_mod.time()

    print(f"\nStarting {total} tasks with {workers} workers...")

    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = []
            for sym, params in tasks:
                futures.append(
                    executor.submit(
                        evaluate_task,
                        sym,
                        params,
                        candles[sym],
                        initial_cash,
                        quantity,
                        interval,
                    )
                )

            done_count = 0
            for future in as_completed(futures):
                results.append(future.result())
                done_count += 1
                _report_progress(done_count, total, start_time)
    else:
        # Sequential fallback
        for i, (sym, params) in enumerate(tasks, start=1):
            results.append(
                evaluate_task(sym, params, candles[sym], initial_cash, quantity, interval)
            )
            _report_progress(i, total, start_time)

    print()  # Final newline after progress
    return results


def run_filter_search(
    tasks: list[tuple[str, dict]],
    candles: dict[str, pd.DataFrame],
    initial_cash: Decimal,
    quantity: int,
    interval: str,
    rvol_lookback_days: int = 20,
) -> list[dict]:
    """Run filter-search tasks sequentially, applying RVOL pre-filter per task."""
    results = []
    total = len(tasks)
    start_time = time_mod.time()

    print(f"\nStarting {total} filter-search tasks (sequential)...")

    for i, (sym, params) in enumerate(tasks, start=1):
        sym_candles = candles[sym]

        # Apply RVOL pre-filter: filter to days where RVOL >= threshold.
        min_rvol = params.get("min_first_window_rvol")
        if min_rvol is not None:
            mwm = int(params.get("momentum_window_minutes", 15))
            sym_candles = filter_candles_by_rvol(sym_candles, min_rvol, mwm, rvol_lookback_days)

        row = evaluate_task(sym, params, sym_candles, initial_cash, quantity, interval)
        results.append(row)
        _report_progress(i, total, start_time)

    print()  # Final newline
    return results


def run_filter_search_split(
    tasks: list[tuple[str, dict]],
    candles: dict[str, pd.DataFrame],
    initial_cash: Decimal,
    quantity: int,
    interval: str,
    train_start: date | None,
    train_end: date | None,
    test_start: date | None,
    test_end: date | None,
    rvol_lookback_days: int = 20,
) -> list[dict]:
    """Run each filter combo on train and test periods separately.

    Each result row contains train_* and test_* prefixed metric columns plus
    rejection flags.  RVOL pre-filter is applied independently per period
    (each period computes its own rolling average from the filtered window).
    """
    train_raw = {
        sym: filter_candles_by_date_range(df, train_start, train_end) for sym, df in candles.items()
    }
    test_raw = {
        sym: filter_candles_by_date_range(df, test_start, test_end) for sym, df in candles.items()
    }

    _metric_keys = (
        "total_pnl",
        "gross_pnl",
        "total_fees",
        "trade_count",
        "win_rate",
        "profit_factor",
        "avg_gross_pnl",
        "fees_per_trade",
    )

    results: list[dict] = []
    total = len(tasks) * 2
    done = 0
    start_time = time_mod.time()
    print(f"\nStarting {len(tasks)} combos x 2 periods = {total} backtest runs (sequential)...")

    for sym, params in tasks:
        min_rvol = params.get("min_first_window_rvol")
        mwm = int(params.get("momentum_window_minutes", 15))

        # ── Train ─────────────────────────────────────────────────────
        tr = train_raw[sym]
        if min_rvol is not None:
            tr = filter_candles_by_rvol(tr, min_rvol, mwm, rvol_lookback_days)
        train_row = evaluate_task(sym, params, tr, initial_cash, quantity, interval)
        done += 1
        _report_progress(done, total, start_time)

        # ── Test ──────────────────────────────────────────────────────
        te = test_raw[sym]
        if min_rvol is not None:
            te = filter_candles_by_rvol(te, min_rvol, mwm, rvol_lookback_days)
        test_row = evaluate_task(sym, params, te, initial_cash, quantity, interval)
        done += 1
        _report_progress(done, total, start_time)

        # ── Merge ─────────────────────────────────────────────────────
        result = _params_to_row(params)
        result["symbol"] = sym
        result["error"] = train_row.get("error") or test_row.get("error")
        for k in _metric_keys:
            result[f"train_{k}"] = train_row.get(k)
            result[f"test_{k}"] = test_row.get(k)

        reject_reason = _compute_rejection(
            test_row.get("trade_count"),
            test_row.get("total_pnl"),
            train_row.get("total_pnl"),
        )
        result["rejected"] = reject_reason is not None
        result["reject_reason"] = reject_reason
        results.append(result)

    print()
    return results


def _report_progress(done: int, total: int, start_time: float):
    elapsed = time_mod.time() - start_time
    avg = elapsed / done if done > 0 else 0
    rem = (total - done) * avg
    print(
        f"\r  Progress: {done}/{total} ({done / total:.1%}) | "
        f"Elapsed: {elapsed:.1f}s | Avg: {avg:.2f}s/t | ETA: {rem:.1f}s",
        end="",
        flush=True,
    )


def save_final(
    results: list[dict],
    output_dir: Path,
    prefix: str = "first_hour_symbol_validation",
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    def sort_key(r):
        return (
            r.get("symbol", ""),
            -(r.get("total_pnl") if r.get("total_pnl") is not None else -1e9),
        )

    sorted_results = sorted(results, key=sort_key)

    csv_path = output_dir / f"{prefix}.csv"
    json_path = output_dir / f"{prefix}.json"

    pd.DataFrame(sorted_results).to_csv(csv_path, index=False)
    with open(json_path, "w") as f:
        json.dump(sorted_results, f, indent=2, default=str)

    print(f"\nSaved {len(results)} results to:")
    print(f"  {csv_path}")
    print(f"  {json_path}")
    return csv_path, json_path


def print_filter_search_results(
    results: list[dict],
    baselines: dict[str, dict] | None = None,
) -> None:
    """Print summary tables for filter-search results."""
    valid = [r for r in results if r.get("error") is None and r.get("total_pnl") is not None]

    if not valid:
        print("No valid results.")
        return

    baseline_trades: dict[str, int] = {}
    if baselines:
        for sym, bl in baselines.items():
            baseline_trades[sym] = bl.get("trade_count", 9999)

    def _fmt(r: dict) -> str:
        sym = r.get("symbol", "?")
        af = r.get("min_first_window_abs_move")
        ar = r.get("min_opening_range_abs")
        rv = r.get("min_first_window_rvol")
        tc = r.get("trade_count", "?")
        net = r.get("total_pnl") or 0.0
        gross = r.get("gross_pnl")
        fees = r.get("total_fees")
        fdr = r.get("fee_drag_ratio")
        gpnn = r.get("gross_positive_net_negative")
        fdr_str = f"{fdr:.2f}" if fdr is not None else "None"
        return (
            f"  {sym:<10} abs_move={str(af):<5} abs_range={str(ar):<5} rvol={str(rv):<5} "
            f"trades={str(tc):<5} net={net:>9.1f} gross={str(round(gross, 1) if gross else gross):<8} "
            f"fees={str(round(fees, 1) if fees else fees):<8} fdr={fdr_str:<6} gpnn={gpnn}"
        )

    def _warn_low_count(r: dict) -> None:
        tc = r.get("trade_count") or 0
        if tc < 20:
            print(f"  *** WARNING: trade_count={tc} < 20 — results unreliable ***")

    print("\n=== TOP 10 BY NET P&L ===")
    by_net = sorted(valid, key=lambda r: r.get("total_pnl") or -1e9, reverse=True)
    for r in by_net[:10]:
        _warn_low_count(r)
        print(_fmt(r))

    print("\n=== TOP 10 BY GROSS P&L (lower trade count than baseline) ===")

    def _below_baseline_trades(r: dict) -> bool:
        sym = r.get("symbol", "")
        bl_tc = baseline_trades.get(sym, 9999)
        tc = r.get("trade_count") or 9999
        return tc < bl_tc

    candidates = [r for r in valid if _below_baseline_trades(r)]
    by_gross = sorted(candidates, key=lambda r: r.get("gross_pnl") or -1e9, reverse=True)
    if by_gross:
        for r in by_gross[:10]:
            _warn_low_count(r)
            print(_fmt(r))
    else:
        print("  (no results with lower trade count than baseline)")

    print("\n=== TOP CONFIGS REDUCING TRADES BY >=40% ===")

    def _trade_reduction_pct(r: dict) -> float:
        sym = r.get("symbol", "")
        bl_tc = baseline_trades.get(sym, 0)
        tc = r.get("trade_count") or 0
        if bl_tc == 0:
            return 0.0
        return (bl_tc - tc) / bl_tc

    reducing = [r for r in valid if _trade_reduction_pct(r) >= 0.40]
    by_reduction = sorted(reducing, key=lambda r: r.get("gross_pnl") or -1e9, reverse=True)
    if by_reduction:
        for r in by_reduction[:15]:
            red_pct = _trade_reduction_pct(r)
            _warn_low_count(r)
            print(f"  [{red_pct:.0%} reduction] {_fmt(r).strip()}")
    else:
        print("  (no configs achieved >=40% trade reduction)")

    if baselines:
        print("\n=== BASELINE COMPARISON ===")
        for sym, bl in baselines.items():
            print(
                f"  {sym}: baseline net={bl.get('total_pnl')}, "
                f"gross={bl.get('gross_pnl')}, fees={bl.get('total_fees')}, "
                f"trades={bl.get('trade_count')}"
            )


def print_train_test_filter_results(
    results: list[dict],
    train_start: date | None = None,
    train_end: date | None = None,
    test_start: date | None = None,
    test_end: date | None = None,
) -> None:
    """Print train/test split results: survivors, rejection breakdown, RVOL comparison."""
    valid = [r for r in results if r.get("error") is None]
    survivors = [r for r in valid if not r.get("rejected", True)]
    rejected_list = [r for r in valid if r.get("rejected", True)]

    print(
        f"\n=== TRAIN/TEST SPLIT ANALYSIS "
        f"(train={train_start} to {train_end}, test={test_start} to {test_end}) ==="
    )
    print(f"Total: {len(valid)} | Survivors: {len(survivors)} | Rejected: {len(rejected_list)}")

    def _n(v, fmt: str = ".1f") -> str:
        if v is None:
            return "None"
        try:
            return format(float(v), fmt)
        except (TypeError, ValueError):
            return str(v)

    def _fmt_row(r: dict) -> str:
        sym = r.get("symbol", "?")
        af = r.get("min_first_window_abs_move")
        ar = r.get("min_opening_range_abs")
        rv = r.get("min_first_window_rvol")
        rr = r.get("reject_reason") or "PASS"
        return (
            f"  {sym:<10} abs_move={str(af):<5} abs_range={str(ar):<5} rvol={str(rv):<5} | "
            f"TRAIN net={_n(r.get('train_total_pnl')):<8} "
            f"gross={_n(r.get('train_gross_pnl')):<8} "
            f"tc={str(r.get('train_trade_count') or '?'):<4} "
            f"PF={_n(r.get('train_profit_factor'), '.2f'):<6} | "
            f"TEST net={_n(r.get('test_total_pnl')):<8} "
            f"gross={_n(r.get('test_gross_pnl')):<8} "
            f"tc={str(r.get('test_trade_count') or '?'):<4} "
            f"PF={_n(r.get('test_profit_factor'), '.2f'):<6} | {rr}"
        )

    if survivors:
        print("\n=== SURVIVORS (pass all rejection rules) ===")
        by_test_net = sorted(survivors, key=lambda r: r.get("test_total_pnl") or -1e9, reverse=True)
        for r in by_test_net:
            print(_fmt_row(r))
    else:
        print("\n=== SURVIVORS: none passed all rejection rules ===")

    # Rejection breakdown by reason
    print(f"\n=== REJECTION BREAKDOWN ({len(rejected_list)} combos) ===")
    by_reason: dict[str, int] = {}
    for r in rejected_list:
        reason = r.get("reject_reason") or "unknown"
        bucket = reason if not reason.startswith("test_trades=") else "test_trades<20"
        by_reason[bucket] = by_reason.get(bucket, 0) + 1
    for bucket, count in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        print(f"  {bucket}: {count} combos")

    # RVOL comparison: base filters only (abs_move=None, abs_range=None)
    symbols_in_results = sorted({r.get("symbol") for r in valid if r.get("symbol")})
    print("\n=== RVOL COMPARISON (abs_move=None, abs_range=None) ===")
    for sym in symbols_in_results:
        printed_header = False
        for rv in [None, 1.2, 1.5]:
            matching = [
                r
                for r in valid
                if r.get("symbol") == sym
                and r.get("min_first_window_rvol") == rv
                and r.get("min_first_window_abs_move") is None
                and r.get("min_opening_range_abs") is None
            ]
            if matching:
                if not printed_header:
                    print(f"\n  {sym}:")
                    printed_header = True
                print(_fmt_row(matching[0]))

    # Robustness verdict for ICICIBANK RVOL=1.2
    if "ICICIBANK" in symbols_in_results:
        print("\n=== ROBUSTNESS VERDICT: ICICIBANK RVOL=1.2 ===")
        rvol12 = [
            r
            for r in valid
            if r.get("symbol") == "ICICIBANK"
            and r.get("min_first_window_rvol") == 1.2
            and r.get("min_first_window_abs_move") is None
            and r.get("min_opening_range_abs") is None
        ]
        if rvol12:
            r = rvol12[0]
            train_net = r.get("train_total_pnl")
            test_net = r.get("test_total_pnl")
            test_tc = r.get("test_trade_count") or 0
            rr = r.get("reject_reason") or "PASS"
            print(f"  Train net={_n(train_net)}, Test net={_n(test_net)}, Test trades={test_tc}")
            if not r.get("rejected", True):
                print("  VERDICT: ROBUST — positive in both train and test periods.")
            elif rr.startswith("test_trades="):
                print(
                    f"  VERDICT: INCONCLUSIVE — too few test trades ({test_tc}); "
                    "cannot distinguish signal from luck."
                )
            elif rr in ("test_net<=0", "train_pos_test_neg"):
                print("  VERDICT: IN-SAMPLE LUCK — profitable in train but not in test.")
            else:
                print(f"  VERDICT: REJECTED ({rr})")
        else:
            print("  No data for ICICIBANK RVOL=1.2 (abs_move=None, abs_range=None).")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--fast-filter-search", action="store_true")
    parser.add_argument("--sample-months", nargs="+", default=[])
    parser.add_argument("--symbols", nargs="+")
    parser.add_argument("--max-combos", type=int)
    parser.add_argument("--max-combinations-per-symbol", type=int)
    parser.add_argument("--data-dir", default=str(_DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default=str(_DEFAULT_OUTPUT_DIR))
    parser.add_argument("--rvol-lookback-days", type=int, default=20)
    parser.add_argument(
        "--train-start",
        type=date.fromisoformat,
        default=date(2025, 1, 1),
    )
    parser.add_argument(
        "--train-end",
        type=date.fromisoformat,
        default=date(2025, 9, 30),
    )
    parser.add_argument(
        "--test-start",
        type=date.fromisoformat,
        default=date(2025, 10, 1),
    )
    parser.add_argument(
        "--test-end",
        type=date.fromisoformat,
        default=date(2026, 1, 31),
    )

    args = parser.parse_args(argv)

    # --max-combinations-per-symbol takes precedence over --max-combos.
    max_combos = args.max_combinations_per_symbol or args.max_combos

    if args.fast_filter_search:
        print("\nFAST-FILTER-SEARCH MODE: sweeping selectivity filters with train/test split")
        symbols = args.symbols if args.symbols else _FAST_SYMBOLS
        max_combos_fs = max_combos or 48

        print(f"Symbols: {symbols}")
        print(
            f"Train: {args.train_start} to {args.train_end} | "
            f"Test: {args.test_start} to {args.test_end}"
        )
        data_dir = Path(args.data_dir)
        candles = load_all_candles(symbols, data_dir, _DEFAULT_INTERVAL)
        if not candles:
            print("No data found.")
            sys.exit(1)

        symbols = [s for s in symbols if s in candles]
        tasks = build_filter_search_tasks(symbols, max_combos_fs)

        split_results = run_filter_search_split(
            tasks,
            candles,
            _DEFAULT_INITIAL_CASH,
            _DEFAULT_QUANTITY,
            _DEFAULT_INTERVAL,
            train_start=args.train_start,
            train_end=args.train_end,
            test_start=args.test_start,
            test_end=args.test_end,
            rvol_lookback_days=args.rvol_lookback_days,
        )

        print_train_test_filter_results(
            split_results,
            train_start=args.train_start,
            train_end=args.train_end,
            test_start=args.test_start,
            test_end=args.test_end,
        )
        save_final(
            split_results,
            Path(args.output_dir),
            prefix="first_hour_filter_search_split",
        )
        return

    symbols = args.symbols if args.symbols else _ALL_SYMBOLS
    if args.fast:
        print("\nFAST MODE: exploratory only")
        symbols = _FAST_SYMBOLS
        max_combos = max_combos or 25

    print(f"Symbols: {symbols}")
    print(f"Workers: {args.workers}")

    data_dir = Path(args.data_dir)
    candles = load_all_candles(symbols, data_dir, _DEFAULT_INTERVAL)
    if not candles:
        print("No data found.")
        sys.exit(1)

    if args.sample_months:
        candles = filter_candles(candles, args.sample_months)
        # Refresh symbols list in case some were filtered out
        symbols = list(candles.keys())

    tasks = build_tasks(symbols, PARAM_GRID, max_combos)
    results = run_parallel(
        tasks,
        candles,
        args.workers,
        _DEFAULT_INITIAL_CASH,
        _DEFAULT_QUANTITY,
        _DEFAULT_INTERVAL,
    )

    save_final(results, Path(args.output_dir))


if __name__ == "__main__":
    main()
