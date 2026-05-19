"""Tests for sweep_first_hour_momentum_params.py.

Focuses on: grid construction, symbol loading, result structure, saving,
top-results printing, and absence of live-trading imports.
All tests use synthetic in-memory data — no real files, no broker calls.
"""

from __future__ import annotations

import json
import sys
from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from sweep_first_hour_momentum_params import (  # noqa: E402
    PARAM_GRID,
    build_grid,
    load_candles,
    print_top_results,
    run_single,
    run_sweep,
    save_results,
)

# ---------------------------------------------------------------------------
# Synthetic candle data
# ---------------------------------------------------------------------------


def _make_candles(n_bars: int = 30) -> dict[str, pd.DataFrame]:
    """5 uptrend window bars then flat bars — enough to test sweep mechanics."""
    rows = []
    for i in range(n_bars):
        c = 100.0 + i * 0.5
        rows.append(
            {
                "timestamp": pd.Timestamp(f"2024-01-15 09:{15 + i:02d}:00"),
                "open": c,
                "high": c + 1,
                "low": c - 1,
                "close": c,
                "volume": 1000,
            }
        )
    return {"RELIANCE": pd.DataFrame(rows)}


def _mini_grid() -> dict[str, list]:
    """1-combination grid for fast engine tests."""
    return {
        "momentum_window_minutes": [5],
        "min_first_window_return_bps": [100.0],
        "latest_entry_time": [time(12, 0)],
        "stop_loss_bps": [100.0],
        "target_bps": [None],
        "allow_shorts": [False],
        "max_trades_per_symbol_per_day": [1],
    }


# ---------------------------------------------------------------------------
# Tests: build_grid
# ---------------------------------------------------------------------------


class TestBuildGrid:
    def test_full_grid_count(self):
        combos = build_grid()
        # 3 * 4 * 3 * 3 * 3 * 1 * 1 = 324
        assert len(combos) == 324

    def test_combo_has_all_expected_keys(self):
        combos = build_grid()
        expected = set(PARAM_GRID.keys())
        for combo in combos:
            assert set(combo.keys()) == expected

    def test_max_combinations_limits_count(self):
        combos = build_grid(max_combinations=10)
        assert len(combos) == 10

    def test_max_combinations_larger_than_grid_returns_all(self):
        combos = build_grid(max_combinations=9999)
        assert len(combos) == 324

    def test_custom_grid_produces_correct_count(self):
        custom = {"a": [1, 2], "b": [3, 4, 5]}
        combos = build_grid(grid=custom)
        assert len(combos) == 6

    def test_grid_contains_none_target(self):
        combos = build_grid()
        none_count = sum(1 for c in combos if c["target_bps"] is None)
        assert none_count > 0

    def test_combos_are_unique(self):
        combos = build_grid()
        strings = [str(sorted((k, str(v)) for k, v in c.items())) for c in combos]
        assert len(strings) == len(set(strings))


# ---------------------------------------------------------------------------
# Tests: load_candles
# ---------------------------------------------------------------------------


class TestLoadCandles:
    def test_loads_existing_parquet(self, tmp_path: Path):
        sym_dir = tmp_path / "candles" / "NSE" / "RELIANCE"
        sym_dir.mkdir(parents=True)
        df = pd.DataFrame([{"timestamp": pd.Timestamp("2024-01-15 09:15:00"), "close": 100.0}])
        df.to_parquet(sym_dir / "minute.parquet")
        candles = load_candles(["RELIANCE"], tmp_path, "minute")
        assert "RELIANCE" in candles

    def test_missing_symbol_skipped(self, tmp_path: Path, capsys):
        candles = load_candles(["GHOST"], tmp_path, "minute")
        assert "GHOST" not in candles
        assert "skip" in capsys.readouterr().out.lower()

    def test_only_loaded_symbols_returned(self, tmp_path: Path):
        sym_dir = tmp_path / "candles" / "NSE" / "RELIANCE"
        sym_dir.mkdir(parents=True)
        df = pd.DataFrame([{"timestamp": pd.Timestamp("2024-01-15 09:15:00"), "close": 100.0}])
        df.to_parquet(sym_dir / "minute.parquet")
        candles = load_candles(["RELIANCE", "INFY"], tmp_path, "minute")
        assert set(candles.keys()) == {"RELIANCE"}

    def test_corrupt_file_skipped(self, tmp_path: Path, capsys):
        sym_dir = tmp_path / "candles" / "NSE" / "BADFILE"
        sym_dir.mkdir(parents=True)
        (sym_dir / "minute.parquet").write_bytes(b"not parquet")
        candles = load_candles(["BADFILE"], tmp_path, "minute")
        assert "BADFILE" not in candles
        assert "skip" in capsys.readouterr().out.lower()

    def test_empty_symbol_list_returns_empty(self, tmp_path: Path):
        assert load_candles([], tmp_path, "minute") == {}


# ---------------------------------------------------------------------------
# Tests: run_single
# ---------------------------------------------------------------------------


class TestRunSingle:
    def _params(self) -> dict:
        return {
            "momentum_window_minutes": 5,
            "min_first_window_return_bps": 100.0,
            "latest_entry_time": time(12, 0),
            "stop_loss_bps": 100.0,
            "target_bps": None,
            "allow_shorts": False,
            "max_trades_per_symbol_per_day": 1,
        }

    def test_returns_dict(self):
        candles = _make_candles()
        row = run_single(candles, self._params(), Decimal("100000"), 10, "minute")
        assert isinstance(row, dict)

    def test_result_has_required_keys(self):
        candles = _make_candles()
        row = run_single(candles, self._params(), Decimal("100000"), 10, "minute")
        for key in ("total_pnl", "total_fees", "max_drawdown", "trade_count"):
            assert key in row

    def test_no_error_on_valid_params(self):
        candles = _make_candles()
        row = run_single(candles, self._params(), Decimal("100000"), 10, "minute")
        assert row.get("error") is None

    def test_invalid_config_returns_error_row(self):
        params = self._params()
        params["stop_loss_bps"] = 0.0  # invalid
        candles = _make_candles()
        row = run_single(candles, params, Decimal("100000"), 10, "minute")
        assert row.get("error") is not None
        assert row.get("total_pnl") is None

    def test_time_serialised_as_string(self):
        candles = _make_candles()
        row = run_single(candles, self._params(), Decimal("100000"), 10, "minute")
        assert isinstance(row.get("latest_entry_time"), str)

    def test_target_none_preserved(self):
        candles = _make_candles()
        row = run_single(candles, self._params(), Decimal("100000"), 10, "minute")
        assert row.get("target_bps") is None


# ---------------------------------------------------------------------------
# Tests: metrics correctness (gross_pnl, profit_factor, average_trade_pnl)
# ---------------------------------------------------------------------------


def _make_entry_exit_candles() -> dict[str, pd.DataFrame]:
    """5 uptrend window bars + 1 entry bar + 1 stop-loss bar → 1 losing round-trip.

    Window (09:15–09:19): closes 100..102 → fw_return=200bps > 100bps threshold.
    Narrow bars (high=c+0.1, low=c-0.1) keep opening_range≈220bps within [30,250].
    Entry bar (09:20):   close=102.5 > fw_close=102; VWAP≈101.25 < 102.5 → BUY.
    Stop bar  (09:21):   stop=102.5*(1-0.01)=101.475; low=101.0 < 101.475 → SELL.
    """
    rows = []
    for i in range(5):
        c = 100.0 + i * 0.5
        rows.append(
            {
                "timestamp": pd.Timestamp(f"2024-01-15 09:{15 + i:02d}:00"),
                "open": c,
                "high": c + 0.1,  # narrow bars: range ≈ 220bps < 250bps default max
                "low": c - 0.1,
                "close": c,
                "volume": 1000,
            }
        )
    rows.append(
        {
            "timestamp": pd.Timestamp("2024-01-15 09:20:00"),
            "open": 102.0,
            "high": 103.5,
            "low": 101.5,
            "close": 102.5,
            "volume": 1000,
        }
    )
    rows.append(
        {
            "timestamp": pd.Timestamp("2024-01-15 09:21:00"),
            "open": 102.5,
            "high": 103.0,
            "low": 101.0,
            "close": 101.5,
            "volume": 1000,
        }
    )
    return {"RELIANCE": pd.DataFrame(rows)}


def _make_entry_profit_candles() -> dict[str, pd.DataFrame]:
    """5 uptrend window bars + 1 entry bar + square-off bar → 1 winning round-trip.

    Narrow bars keep opening_range≈220bps within [30,250].
    The profitable square-off at 15:15 is the only exit; zero losses.
    profit_factor is None (no losing trades → undefined / infinite).
    """
    rows = []
    for i in range(5):
        c = 100.0 + i * 0.5
        rows.append(
            {
                "timestamp": pd.Timestamp(f"2024-01-15 09:{15 + i:02d}:00"),
                "open": c,
                "high": c + 0.1,
                "low": c - 0.1,
                "close": c,
                "volume": 1000,
            }
        )
    rows.append(
        {
            "timestamp": pd.Timestamp("2024-01-15 09:20:00"),
            "open": 102.0,
            "high": 103.5,
            "low": 101.5,
            "close": 102.5,
            "volume": 1000,
        }
    )
    # Square-off at 15:15: price well above entry → profitable trade.
    rows.append(
        {
            "timestamp": pd.Timestamp("2024-01-15 15:15:00"),
            "open": 107.0,
            "high": 109.0,
            "low": 106.0,
            "close": 108.0,
            "volume": 1000,
        }
    )
    return {"RELIANCE": pd.DataFrame(rows)}


def _sweep_params() -> dict:
    return {
        "momentum_window_minutes": 5,
        "min_first_window_return_bps": 100.0,
        "latest_entry_time": time(12, 0),
        "stop_loss_bps": 100.0,
        "target_bps": None,
        "allow_shorts": False,
        "max_trades_per_symbol_per_day": 1,
    }


class TestMetricsFix:
    """Verify that gross_pnl, profit_factor, and average_trade_pnl are correct."""

    def test_gross_pnl_equals_total_pnl_plus_total_fees(self):
        """gross_pnl must equal total_pnl + total_fees for a completed round-trip."""
        row = run_single(
            _make_entry_exit_candles(), _sweep_params(), Decimal("100000"), 10, "minute"
        )
        assert row.get("error") is None
        gp = row["gross_pnl"]
        tp = row["total_pnl"]
        tf = row["total_fees"]
        assert gp is not None and tp is not None and tf is not None
        assert abs(gp - (tp + tf)) < 1.0, (
            f"gross_pnl={gp:.4f} != total_pnl+total_fees={tp + tf:.4f}"
        )

    def test_gross_pnl_formula_independent_of_realized_pnl(self):
        """gross_pnl must not blindly copy m.realized_pnl (which has a FIFO bug).

        For a single-symbol round-trip, realized_pnl deducts only sell fees,
        so it differs from total_pnl + total_fees by the buy-side fees.
        The new formula always satisfies the accounting identity exactly.
        """
        row = run_single(
            _make_entry_exit_candles(), _sweep_params(), Decimal("100000"), 10, "minute"
        )
        assert row.get("error") is None
        gp = row["gross_pnl"]
        tp = row["total_pnl"]
        tf = row["total_fees"]
        # Accounting identity must hold within 1 INR rounding tolerance.
        assert abs(gp - (tp + tf)) < 1.0

    def test_profit_factor_none_when_no_round_trips(self):
        """profit_factor is None when no completed trades exist."""
        # Only 3 bars — window needs 5, so no entry, no fills.
        row = run_single(_make_candles(n_bars=3), _sweep_params(), Decimal("100000"), 10, "minute")
        assert row.get("error") is None
        assert row["profit_factor"] is None

    def test_profit_factor_none_when_all_trades_are_wins(self):
        """profit_factor is None when there are wins but zero losing trades."""
        row = run_single(
            _make_entry_profit_candles(), _sweep_params(), Decimal("100000"), 10, "minute"
        )
        assert row.get("error") is None
        # One profitable trade, zero losses → denominator=0 → profit_factor=None.
        assert row["profit_factor"] is None

    def test_average_trade_pnl_is_total_pnl_divided_by_one_round_trip(self):
        """For a single round-trip, average_trade_pnl must equal total_pnl."""
        row = run_single(
            _make_entry_exit_candles(), _sweep_params(), Decimal("100000"), 10, "minute"
        )
        assert row.get("error") is None
        tp = row["total_pnl"]
        atp = row["average_trade_pnl"]
        tc = row["trade_count"]
        assert tp is not None and atp is not None
        assert tc == 2, f"expected 2 fills (1 round-trip), got {tc}"
        # 1 round-trip → average = total_pnl / 1 = total_pnl
        assert abs(atp - tp) < 0.01, f"average_trade_pnl={atp} != total_pnl={tp}"

    def test_no_consistency_warning_for_fully_closed_position(self):
        """_consistency_warning must be None when all positions are squared off."""
        row = run_single(
            _make_entry_exit_candles(), _sweep_params(), Decimal("100000"), 10, "minute"
        )
        assert row.get("error") is None
        assert row["_consistency_warning"] is None, row["_consistency_warning"]

    def test_csv_gross_pnl_matches_total_pnl_plus_fees(self, tmp_path: Path):
        """Saved CSV must have gross_pnl = total_pnl + total_fees."""
        row = run_single(
            _make_entry_exit_candles(), _sweep_params(), Decimal("100000"), 10, "minute"
        )
        csv_path, _ = save_results([row], tmp_path)
        df = pd.read_csv(csv_path)
        gp = float(df["gross_pnl"].iloc[0])
        tp = float(df["total_pnl"].iloc[0])
        tf = float(df["total_fees"].iloc[0])
        assert abs(gp - (tp + tf)) < 1.0

    def test_json_gross_pnl_matches_total_pnl_plus_fees(self, tmp_path: Path):
        """Saved JSON must have gross_pnl = total_pnl + total_fees."""
        row = run_single(
            _make_entry_exit_candles(), _sweep_params(), Decimal("100000"), 10, "minute"
        )
        _, json_path = save_results([row], tmp_path)
        with json_path.open() as fh:
            data = json.load(fh)
        rec = data[0]
        gp = rec["gross_pnl"]
        tp = rec["total_pnl"]
        tf = rec["total_fees"]
        assert gp is not None and tp is not None and tf is not None
        assert abs(gp - (tp + tf)) < 1.0


# ---------------------------------------------------------------------------
# Tests: run_sweep
# ---------------------------------------------------------------------------


class TestRunSweep:
    def test_returns_one_result_per_combo(self):
        candles = _make_candles()
        combos = build_grid(grid=_mini_grid())
        results = run_sweep(candles, combos, Decimal("100000"), 10, "minute")
        assert len(results) == 1

    def test_results_are_dicts(self):
        candles = _make_candles()
        combos = build_grid(grid=_mini_grid())
        results = run_sweep(candles, combos, Decimal("100000"), 10, "minute")
        assert all(isinstance(r, dict) for r in results)

    def test_trade_count_non_negative(self):
        candles = _make_candles()
        combos = build_grid(grid=_mini_grid())
        results = run_sweep(candles, combos, Decimal("100000"), 10, "minute")
        for r in results:
            if r.get("error") is None:
                assert (r.get("trade_count") or 0) >= 0


# ---------------------------------------------------------------------------
# Tests: save_results
# ---------------------------------------------------------------------------


class TestSaveResults:
    def _fake_results(self) -> list[dict]:
        return [
            {
                "momentum_window_minutes": 30,
                "min_first_window_return_bps": 60,
                "latest_entry_time": "12:00:00",
                "stop_loss_bps": 80,
                "target_bps": None,
                "allow_shorts": False,
                "max_trades_per_symbol_per_day": 1,
                "error": None,
                "total_return": -0.03,
                "total_pnl": -1500.0,
                "gross_pnl": -800.0,
                "total_fees": 700.0,
                "max_drawdown": 0.04,
                "win_rate": 0.4,
                "profit_factor": 0.6,
                "trade_count": 40,
                "average_trade_pnl": -37.5,
                "sharpe_ratio": None,
                "sortino_ratio": None,
            }
        ]

    def test_csv_created(self, tmp_path: Path):
        csv_path, _ = save_results(self._fake_results(), tmp_path)
        assert csv_path.exists()

    def test_json_created(self, tmp_path: Path):
        _, json_path = save_results(self._fake_results(), tmp_path)
        assert json_path.exists()

    def test_json_is_valid(self, tmp_path: Path):
        _, json_path = save_results(self._fake_results(), tmp_path)
        with json_path.open() as fh:
            data = json.load(fh)
        assert isinstance(data, list)
        assert len(data) == 1

    def test_csv_row_count(self, tmp_path: Path):
        results = self._fake_results() * 3
        csv_path, _ = save_results(results, tmp_path)
        df = pd.read_csv(csv_path)
        assert len(df) == 3

    def test_output_dir_created_if_missing(self, tmp_path: Path):
        subdir = tmp_path / "nested" / "dir"
        save_results(self._fake_results(), subdir)
        assert subdir.exists()


# ---------------------------------------------------------------------------
# Tests: print_top_results
# ---------------------------------------------------------------------------


class TestPrintTopResults:
    def _results(self, n: int = 5) -> list[dict]:
        return [
            {
                "momentum_window_minutes": 30,
                "min_first_window_return_bps": 60 + i * 10,
                "latest_entry_time": "12:00:00",
                "stop_loss_bps": 80,
                "target_bps": None,
                "allow_shorts": False,
                "max_trades_per_symbol_per_day": 1,
                "error": None,
                "total_pnl": (i - 2) * 1000.0,
                "profit_factor": 0.5 + i * 0.1,
                "max_drawdown": 0.05 + i * 0.01,
                "win_rate": 0.4,
                "trade_count": 10 + i * 10,
                "average_trade_pnl": (i - 2) * 20.0,
                "sharpe_ratio": None,
                "sortino_ratio": None,
            }
            for i in range(n)
        ]

    def test_no_crash(self, capsys):
        print_top_results(self._results())

    def test_prints_in_sample_warning(self, capsys):
        print_top_results(self._results())
        assert "IN-SAMPLE" in capsys.readouterr().out

    def test_no_crash_empty_results(self, capsys):
        print_top_results([])

    def test_few_trades_message(self, capsys):
        results = self._results(n=2)  # trade_counts: 10, 20; both < 30
        print_top_results(results, min_trades_for_dd=30)
        assert "30" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Tests: no Zerodha dependency
# ---------------------------------------------------------------------------


class TestNoZerodhaDependency:
    def test_sweep_module_no_kiteconnect(self):
        import inspect

        import sweep_first_hour_momentum_params as mod

        assert "kiteconnect" not in inspect.getsource(mod)

    def test_sweep_module_no_zerodha(self):
        import inspect

        import sweep_first_hour_momentum_params as mod

        assert "zerodha" not in inspect.getsource(mod).lower()

    def test_sweep_module_no_live_execution(self):
        import inspect

        import sweep_first_hour_momentum_params as mod

        src = inspect.getsource(mod)
        assert "live_execution" not in src
        assert "place_order" not in src


# ---------------------------------------------------------------------------
# Tests: RVOL filter (validate_first_hour_symbol_specific.py)
# ---------------------------------------------------------------------------


class TestRVOLFilter:
    def _make_vol_candles(
        self, n_days: int, volume: int = 1000, window_minutes: int = 1
    ) -> pd.DataFrame:
        """One bar per day at 09:15 with given volume."""
        rows = []
        for d in range(n_days):
            rows.append(
                {
                    "timestamp": pd.Timestamp(f"2024-01-{d + 1:02d} 09:15:00"),
                    "volume": volume,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                }
            )
        return pd.DataFrame(rows)

    def test_insufficient_history_all_pass(self):
        """< lookback_days prior days → all dates eligible (no crash)."""
        from validate_first_hour_symbol_specific import compute_rvol_eligible_dates

        df = self._make_vol_candles(n_days=5)
        eligible = compute_rvol_eligible_dates(df, window_minutes=1, min_rvol=2.0, lookback_days=20)
        assert len(eligible) == 5

    def test_low_rvol_day_excluded(self):
        """Day with RVOL < threshold is excluded once enough history exists."""
        from validate_first_hour_symbol_specific import compute_rvol_eligible_dates

        # 20 normal days (vol=1000), then 1 very-low-volume day (vol=100).
        rows = []
        for d in range(20):
            rows.append(
                {
                    "timestamp": pd.Timestamp(f"2024-01-{d + 1:02d} 09:15:00"),
                    "volume": 1000,
                }
            )
        rows.append({"timestamp": pd.Timestamp("2024-01-21 09:15:00"), "volume": 100})
        df = pd.DataFrame(rows)
        # day 21: rvol = 100 / 1000 = 0.1 < 1.2 → excluded
        eligible = compute_rvol_eligible_dates(df, window_minutes=1, min_rvol=1.2, lookback_days=20)
        assert len(eligible) == 20  # days 1-20 pass, day 21 does not

    def test_high_rvol_day_included(self):
        """Day with RVOL >= threshold is included."""
        from validate_first_hour_symbol_specific import compute_rvol_eligible_dates

        rows = []
        for d in range(20):
            rows.append(
                {
                    "timestamp": pd.Timestamp(f"2024-01-{d + 1:02d} 09:15:00"),
                    "volume": 1000,
                }
            )
        rows.append({"timestamp": pd.Timestamp("2024-01-21 09:15:00"), "volume": 5000})
        df = pd.DataFrame(rows)
        # day 21: rvol = 5000 / 1000 = 5.0 >= 1.2 → included
        eligible = compute_rvol_eligible_dates(df, window_minutes=1, min_rvol=1.2, lookback_days=20)
        assert len(eligible) == 21

    def test_zero_rolling_avg_day_passes(self):
        """When rolling average volume is 0, RVOL is undefined → day passes."""
        from validate_first_hour_symbol_specific import compute_rvol_eligible_dates

        rows = []
        for d in range(20):
            rows.append(
                {
                    "timestamp": pd.Timestamp(f"2024-01-{d + 1:02d} 09:15:00"),
                    "volume": 0,  # zero volume lookback
                }
            )
        rows.append({"timestamp": pd.Timestamp("2024-01-21 09:15:00"), "volume": 1000})
        df = pd.DataFrame(rows)
        eligible = compute_rvol_eligible_dates(df, window_minutes=1, min_rvol=1.2, lookback_days=20)
        # All 21 pass (days 1-20 insufficient history or zero avg)
        assert len(eligible) == 21

    def test_filter_candles_by_rvol_returns_unchanged_when_none(self):
        """min_rvol=None → all candles returned unchanged."""
        from validate_first_hour_symbol_specific import filter_candles_by_rvol

        df = self._make_vol_candles(n_days=3)
        result = filter_candles_by_rvol(df, min_rvol=None, window_minutes=1)
        assert len(result) == len(df)

    def test_filter_candles_by_rvol_removes_low_volume_day(self):
        """Low-RVOL day is removed from candle DataFrame."""
        from validate_first_hour_symbol_specific import filter_candles_by_rvol

        rows = []
        for d in range(20):
            rows.append(
                {
                    "timestamp": pd.Timestamp(f"2024-01-{d + 1:02d} 09:15:00"),
                    "volume": 1000,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                }
            )
        rows.append(
            {
                "timestamp": pd.Timestamp("2024-01-21 09:15:00"),
                "volume": 10,  # very low: rvol = 0.01 < 1.2
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
            }
        )
        df = pd.DataFrame(rows)
        result = filter_candles_by_rvol(df, min_rvol=1.2, window_minutes=1, lookback_days=20)
        # Day 21 should be removed (only 20 days remain)
        dates = result["timestamp"].dt.date.unique()
        assert len(dates) == 20


# ---------------------------------------------------------------------------
# Tests: fast-filter-search grid and evaluate_task columns
# ---------------------------------------------------------------------------


class TestFastFilterSearch:
    def _vs_params(self) -> dict:
        return {
            "momentum_window_minutes": 5,
            "min_first_window_return_bps": 100.0,
            "latest_entry_time": time(12, 0),
            "stop_loss_bps": 100.0,
            "target_bps": None,
            "allow_shorts": False,
            "max_trades_per_symbol_per_day": 1,
            "min_first_window_abs_move": None,
            "min_opening_range_abs": None,
            "min_first_window_rvol": None,
        }

    def test_filter_search_grid_max_48_combos(self):
        from itertools import product as iproduct

        from validate_first_hour_symbol_specific import FILTER_SEARCH_GRID

        combos = list(iproduct(*FILTER_SEARCH_GRID.values()))
        assert len(combos) <= 48

    def test_filter_search_grid_keys_disjoint_from_base_params(self):
        from validate_first_hour_symbol_specific import (
            FILTER_SEARCH_BASE_PARAMS,
            FILTER_SEARCH_GRID,
        )

        assert set(FILTER_SEARCH_GRID.keys()).isdisjoint(set(FILTER_SEARCH_BASE_PARAMS.keys()))

    def test_evaluate_task_includes_fee_drag_ratio(self):
        from validate_first_hour_symbol_specific import evaluate_task

        candles = _make_entry_exit_candles()["RELIANCE"]
        row = evaluate_task("RELIANCE", self._vs_params(), candles, Decimal("100000"), 10, "minute")
        assert "fee_drag_ratio" in row

    def test_evaluate_task_includes_gross_positive_net_negative(self):
        from validate_first_hour_symbol_specific import evaluate_task

        candles = _make_entry_exit_candles()["RELIANCE"]
        row = evaluate_task("RELIANCE", self._vs_params(), candles, Decimal("100000"), 10, "minute")
        assert "gross_positive_net_negative" in row

    def test_evaluate_task_includes_avg_gross_pnl(self):
        from validate_first_hour_symbol_specific import evaluate_task

        candles = _make_entry_exit_candles()["RELIANCE"]
        row = evaluate_task("RELIANCE", self._vs_params(), candles, Decimal("100000"), 10, "minute")
        assert "avg_gross_pnl" in row

    def test_evaluate_task_includes_fees_per_trade(self):
        from validate_first_hour_symbol_specific import evaluate_task

        candles = _make_entry_exit_candles()["RELIANCE"]
        row = evaluate_task("RELIANCE", self._vs_params(), candles, Decimal("100000"), 10, "minute")
        assert "fees_per_trade" in row

    def test_build_filter_search_tasks_respects_max_combos(self):
        from validate_first_hour_symbol_specific import build_filter_search_tasks

        tasks = build_filter_search_tasks(["RELIANCE"], max_combos_per_symbol=5)
        assert len(tasks) == 5

    def test_build_filter_search_tasks_merges_base_params(self):
        from validate_first_hour_symbol_specific import (
            FILTER_SEARCH_BASE_PARAMS,
            build_filter_search_tasks,
        )

        tasks = build_filter_search_tasks(["RELIANCE"], max_combos_per_symbol=1)
        _, params = tasks[0]
        for k, v in FILTER_SEARCH_BASE_PARAMS.items():
            assert params[k] == v


# ---------------------------------------------------------------------------
# Tests: no live trading imports in validate script and strategy
# ---------------------------------------------------------------------------


class TestNoLiveTradingImports:
    def _parse_import_modules(self, path: Path) -> list[str]:
        import ast

        tree = ast.parse(path.read_text())
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.append(node.module)
        return modules

    def test_validate_script_no_zerodha(self):
        script = (
            Path(__file__).resolve().parents[3]
            / "scripts"
            / "validate_first_hour_symbol_specific.py"
        )
        mods = self._parse_import_modules(script)
        assert not any("zerodha" in m.lower() for m in mods)

    def test_strategy_no_zerodha(self):
        script = (
            Path(__file__).resolve().parents[3]
            / "src"
            / "trading_engine"
            / "strategies"
            / "first_hour_momentum.py"
        )
        mods = self._parse_import_modules(script)
        assert not any("zerodha" in m.lower() for m in mods)

    def test_strategy_no_live_order_placement(self):
        script = (
            Path(__file__).resolve().parents[3]
            / "src"
            / "trading_engine"
            / "strategies"
            / "first_hour_momentum.py"
        )
        src = script.read_text()
        assert "place_order" not in src
        assert "kite.order_place" not in src


# ---------------------------------------------------------------------------
# Helpers for train/test split tests
# ---------------------------------------------------------------------------


def _make_date_candles(n_days: int = 5) -> pd.DataFrame:
    """One bar per day at 09:15 for 2024-01-01 through 2024-01-{n_days}."""
    rows = []
    for d in range(1, n_days + 1):
        rows.append(
            {
                "timestamp": pd.Timestamp(f"2024-01-{d:02d} 09:15:00"),
                "volume": 1000,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
            }
        )
    return pd.DataFrame(rows)


def _make_two_period_candles() -> pd.DataFrame:
    """Two complete trading days (2024-01-15 train, 2024-01-16 test).

    Each day: 5 narrow window bars + entry bar (close>fw_close) + square-off bar.
    Configuration: momentum_window=5, min_return=100bps, stop=100bps, no VWAP filter.
    window bars: high=c+0.1, low=c-0.1 → opening_range ≈ 220bps < 250bps default.
    Entry: close=102.5 > fw_close=102 → BUY; exit at 15:15 at close=108.
    """
    rows = []
    for day_str in ["2024-01-15", "2024-01-16"]:
        for i in range(5):
            c = 100.0 + i * 0.5
            rows.append(
                {
                    "timestamp": pd.Timestamp(f"{day_str} 09:{15 + i:02d}:00"),
                    "open": c,
                    "high": c + 0.1,
                    "low": c - 0.1,
                    "close": c,
                    "volume": 1000,
                }
            )
        rows.append(
            {
                "timestamp": pd.Timestamp(f"{day_str} 09:20:00"),
                "open": 102.0,
                "high": 103.5,
                "low": 101.5,
                "close": 102.5,
                "volume": 1000,
            }
        )
        rows.append(
            {
                "timestamp": pd.Timestamp(f"{day_str} 15:15:00"),
                "open": 107.0,
                "high": 109.0,
                "low": 106.0,
                "close": 108.0,
                "volume": 1000,
            }
        )
    return pd.DataFrame(rows)


def _split_params() -> dict:
    return {
        "momentum_window_minutes": 5,
        "min_first_window_return_bps": 100.0,
        "latest_entry_time": time(12, 0),
        "stop_loss_bps": 100.0,
        "target_bps": None,
        "allow_shorts": False,
        "max_trades_per_symbol_per_day": 1,
        "min_first_window_abs_move": None,
        "min_opening_range_abs": None,
        "min_first_window_rvol": None,
    }


# ---------------------------------------------------------------------------
# Tests: filter_candles_by_date_range
# ---------------------------------------------------------------------------


class TestFilterCandlesByDateRange:
    def test_returns_all_when_both_none(self):
        from validate_first_hour_symbol_specific import filter_candles_by_date_range

        df = _make_date_candles(5)
        result = filter_candles_by_date_range(df, None, None)
        assert len(result) == len(df)

    def test_start_is_inclusive(self):
        from datetime import date

        from validate_first_hour_symbol_specific import filter_candles_by_date_range

        df = _make_date_candles(5)
        result = filter_candles_by_date_range(df, date(2024, 1, 3), None)
        assert len(result) == 3  # days 3, 4, 5

    def test_end_is_inclusive(self):
        from datetime import date

        from validate_first_hour_symbol_specific import filter_candles_by_date_range

        df = _make_date_candles(5)
        result = filter_candles_by_date_range(df, None, date(2024, 1, 3))
        assert len(result) == 3  # days 1, 2, 3

    def test_both_bounds_inclusive(self):
        from datetime import date

        from validate_first_hour_symbol_specific import filter_candles_by_date_range

        df = _make_date_candles(5)
        result = filter_candles_by_date_range(df, date(2024, 1, 2), date(2024, 1, 4))
        assert len(result) == 3  # days 2, 3, 4

    def test_empty_range_returns_empty(self):
        from datetime import date

        from validate_first_hour_symbol_specific import filter_candles_by_date_range

        df = _make_date_candles(5)
        result = filter_candles_by_date_range(df, date(2024, 2, 1), date(2024, 2, 28))
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Tests: _compute_rejection
# ---------------------------------------------------------------------------


class TestComputeRejection:
    def test_no_rejection_when_all_pass(self):
        from validate_first_hour_symbol_specific import _compute_rejection

        assert _compute_rejection(40, 100.0, 50.0) is None

    def test_rejects_low_test_trades(self):
        from validate_first_hour_symbol_specific import _compute_rejection

        r = _compute_rejection(10, 100.0, 50.0)
        assert r is not None
        assert "10" in r

    def test_boundary_20_trades_passes(self):
        from validate_first_hour_symbol_specific import _compute_rejection

        assert _compute_rejection(20, 100.0, 50.0) is None

    def test_rejects_test_net_zero_train_negative(self):
        from validate_first_hour_symbol_specific import _compute_rejection

        r = _compute_rejection(40, 0.0, -50.0)
        assert r == "test_net<=0"

    def test_rejects_test_net_negative_train_negative(self):
        from validate_first_hour_symbol_specific import _compute_rejection

        r = _compute_rejection(40, -100.0, -50.0)
        assert r == "test_net<=0"

    def test_train_pos_test_neg_reported_as_overfitting(self):
        from validate_first_hour_symbol_specific import _compute_rejection

        r = _compute_rejection(40, -100.0, 50.0)
        assert r == "train_pos_test_neg"

    def test_none_trade_count_treated_as_zero(self):
        from validate_first_hour_symbol_specific import _compute_rejection

        r = _compute_rejection(None, 100.0, 50.0)
        assert r is not None  # 0 < 20 → rejected


# ---------------------------------------------------------------------------
# Tests: run_filter_search_split
# ---------------------------------------------------------------------------


class TestRunFilterSearchSplit:
    _TRAIN = (date(2024, 1, 15), date(2024, 1, 15))
    _TEST = (date(2024, 1, 16), date(2024, 1, 16))

    def _run(self, tasks=None):
        from validate_first_hour_symbol_specific import run_filter_search_split

        candles = {"RELIANCE": _make_two_period_candles()}
        if tasks is None:
            tasks = [("RELIANCE", _split_params())]
        return run_filter_search_split(
            tasks,
            candles,
            Decimal("100000"),
            10,
            "minute",
            *self._TRAIN,
            *self._TEST,
        )

    def test_returns_one_result_per_task(self):
        results = self._run()
        assert len(results) == 1

    def test_result_has_train_columns(self):
        r = self._run()[0]
        assert "train_total_pnl" in r
        assert "train_trade_count" in r
        assert "train_profit_factor" in r

    def test_result_has_test_columns(self):
        r = self._run()[0]
        assert "test_total_pnl" in r
        assert "test_trade_count" in r
        assert "test_profit_factor" in r

    def test_rejected_and_reason_keys_present(self):
        r = self._run()[0]
        assert "rejected" in r
        assert "reject_reason" in r

    def test_rejected_when_test_trades_below_20(self):
        """Single test-day trade → test_trade_count=2 < 20 → rejected."""
        r = self._run()[0]
        assert r["rejected"] is True
        assert r["reject_reason"] is not None

    def test_multiple_tasks_all_returned(self):
        p1 = {**_split_params(), "stop_loss_bps": 60.0}
        p2 = {**_split_params(), "stop_loss_bps": 80.0}
        results = self._run(tasks=[("RELIANCE", p1), ("RELIANCE", p2)])
        assert len(results) == 2
