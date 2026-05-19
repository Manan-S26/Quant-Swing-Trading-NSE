"""Tests for validate_selected_first_hour.py and evaluate_task slippage_bps."""

from __future__ import annotations

import sys
from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_first_hour_symbol_specific import evaluate_task  # noqa: E402

# ---------------------------------------------------------------------------
# Shared candle helpers
# ---------------------------------------------------------------------------


def _make_entry_exit_candles_df() -> pd.DataFrame:
    """15 first-window bars (09:15–09:29), then entry + stop-loss exit.

    Window bars: 14 flat bars at 100.0 (09:15–09:28) + 1 up-bar at 09:29.
    fw_open=100.0, fw_close=100.5 → return=50bps > 40bps threshold.
    fw_high=100.2, fw_low=99.8 → orb≈40bps (within [30, 250] default range).
    Entry bar 09:30: close=101.0 > fw_close=100.5 → BUY triggered.
    Stop bar  09:31: low=100.0 < stop(101.0*(1-0.006)=100.394) → SELL at stop.
    """
    rows = []
    # 14 flat bars 09:15–09:28
    for i in range(14):
        rows.append(
            {
                "timestamp": pd.Timestamp(f"2024-01-15 09:{15 + i:02d}:00"),
                "open": 100.0,
                "high": 100.1,
                "low": 99.9,
                "close": 100.0,
                "volume": 1000,
            }
        )
    # 15th window bar 09:29 — close above open, range wide enough for orb filter
    rows.append(
        {
            "timestamp": pd.Timestamp("2024-01-15 09:29:00"),
            "open": 100.0,
            "high": 100.2,
            "low": 99.8,
            "close": 100.5,
            "volume": 1000,
        }
    )
    # Entry bar 09:30
    rows.append(
        {
            "timestamp": pd.Timestamp("2024-01-15 09:30:00"),
            "open": 100.5,
            "high": 101.5,
            "low": 100.4,
            "close": 101.0,
            "volume": 1000,
        }
    )
    # Stop bar 09:31
    rows.append(
        {
            "timestamp": pd.Timestamp("2024-01-15 09:31:00"),
            "open": 101.0,
            "high": 101.2,
            "low": 100.0,
            "close": 100.2,
            "volume": 1000,
        }
    )
    return pd.DataFrame(rows)


def _fhm_params() -> dict:
    return {
        "momentum_window_minutes": 15,
        "min_first_window_return_bps": 40.0,
        "latest_entry_time": time(10, 30),
        "stop_loss_bps": 60.0,
        "target_bps": None,
        "allow_shorts": False,
        "max_trades_per_symbol_per_day": 1,
    }


# ---------------------------------------------------------------------------
# TestEvaluateTaskSlippageBps
# ---------------------------------------------------------------------------


class TestEvaluateTaskSlippageBps:
    def test_slippage_bps_param_accepted(self):
        """evaluate_task must accept slippage_bps keyword without error."""
        df = _make_entry_exit_candles_df()
        row = evaluate_task(
            "TEST",
            _fhm_params(),
            df,
            Decimal("100000"),
            10,
            "minute",
            slippage_bps=Decimal("2"),
        )
        assert row.get("error") is None

    def test_higher_slippage_reduces_net_pnl(self):
        """net P&L with bps=10 must be lower (more negative) than bps=2 when trades exist."""
        df = _make_entry_exit_candles_df()
        row_low = evaluate_task(
            "TEST",
            _fhm_params(),
            df,
            Decimal("100000"),
            10,
            "minute",
            slippage_bps=Decimal("2"),
        )
        row_high = evaluate_task(
            "TEST",
            _fhm_params(),
            df,
            Decimal("100000"),
            10,
            "minute",
            slippage_bps=Decimal("10"),
        )
        assert row_low.get("error") is None
        assert row_high.get("error") is None
        assert row_low.get("trade_count", 0) >= 1, "candle fixture must trigger at least one trade"
        assert row_high["total_pnl"] < row_low["total_pnl"]


from validate_selected_first_hour import (  # noqa: E402
    SELECTED_CONFIGS,
    SLIPPAGE_SCENARIOS,
    build_month_windows,
    build_quarter_windows,
    check_insufficient_evidence,
    check_stress_rejection,
    run_config_on_slice,
    run_extended_validation,
)


def _make_flat_candles(n_days: int = 3) -> pd.DataFrame:
    """Flat candles that do not trigger any trades (not enough momentum)."""
    rows = []
    for day in range(n_days):
        d = date(2025, 1, 1 + day)
        for bar in range(30):
            ts = pd.Timestamp(f"{d} 09:{15 + bar:02d}:00")
            rows.append(
                {
                    "timestamp": ts,
                    "open": 100.0,
                    "high": 100.1,
                    "low": 99.9,
                    "close": 100.0,
                    "volume": 1000,
                }
            )
    return pd.DataFrame(rows)


def _make_multi_month_candles() -> pd.DataFrame:
    """Two months of flat bars — Jan and Feb 2025."""
    rows = []
    for month in [1, 2]:
        for day in [2, 3, 6, 7]:
            d = date(2025, month, day)
            for bar in range(5):
                ts = pd.Timestamp(f"{d} 09:{15 + bar:02d}:00")
                rows.append(
                    {
                        "timestamp": ts,
                        "open": 100.0,
                        "high": 100.1,
                        "low": 99.9,
                        "close": 100.0,
                        "volume": 1000,
                    }
                )
    return pd.DataFrame(rows)


class TestRunConfigOnSlice:
    def _cfg(self) -> dict:
        return SELECTED_CONFIGS[0]  # ICICIBANK RVOL=1.2

    def test_returns_required_keys(self):
        df = _make_flat_candles()
        cfg = self._cfg()
        row = run_config_on_slice(
            config_label=cfg["label"],
            symbol=cfg["symbol"],
            params=cfg["params"],
            min_rvol=None,
            candle_df=df,
            start_date=None,
            end_date=None,
            slippage_label="base",
            slippage_bps=Decimal("2"),
            window_label="full",
            window_type="full",
            initial_cash=Decimal("100000"),
            quantity=10,
            interval="minute",
        )
        for key in (
            "config_label",
            "symbol",
            "window_label",
            "window_type",
            "slippage_label",
            "slippage_bps",
            "total_pnl",
            "trade_count",
            "insufficient_evidence",
            "stress_rejected",
        ):
            assert key in row, f"missing key: {key}"

    def test_empty_candles_returns_no_data_error(self):
        empty_df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        cfg = self._cfg()
        row = run_config_on_slice(
            config_label=cfg["label"],
            symbol=cfg["symbol"],
            params=cfg["params"],
            min_rvol=None,
            candle_df=empty_df,
            start_date=None,
            end_date=None,
            slippage_label="base",
            slippage_bps=Decimal("2"),
            window_label="full",
            window_type="full",
            initial_cash=Decimal("100000"),
            quantity=10,
            interval="minute",
        )
        assert row.get("error") == "no_data"

    def test_date_filter_applied(self):
        """Restricting to a window outside all candles yields no_data error."""
        df = _make_flat_candles(3)  # dates 2025-01-01 to 2025-01-03
        cfg = self._cfg()
        row = run_config_on_slice(
            config_label=cfg["label"],
            symbol=cfg["symbol"],
            params=cfg["params"],
            min_rvol=None,
            candle_df=df,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            slippage_label="base",
            slippage_bps=Decimal("2"),
            window_label="2026-01",
            window_type="month",
            initial_cash=Decimal("100000"),
            quantity=10,
            interval="minute",
        )
        assert row.get("error") == "no_data"

    def test_slippage_label_in_output(self):
        df = _make_flat_candles()
        cfg = self._cfg()
        row = run_config_on_slice(
            config_label=cfg["label"],
            symbol=cfg["symbol"],
            params=cfg["params"],
            min_rvol=None,
            candle_df=df,
            start_date=None,
            end_date=None,
            slippage_label="+2tick",
            slippage_bps=Decimal("4"),
            window_label="full",
            window_type="full",
            initial_cash=Decimal("100000"),
            quantity=10,
            interval="minute",
        )
        assert row.get("slippage_label") == "+2tick"
        assert row.get("slippage_bps") == 4


class TestBuildMonthWindows:
    def test_empty_candles_returns_empty(self):
        empty = {
            "SYM": pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        }
        assert build_month_windows(empty) == []

    def test_single_month_returns_one_window(self):
        df = _make_flat_candles(3)  # Jan 2025 only
        windows = build_month_windows({"SYM": df})
        assert len(windows) == 1
        label, start, end = windows[0]
        assert label == "2025-01"
        assert start == date(2025, 1, 1)
        assert end == date(2025, 1, 31)

    def test_two_months_returns_two_windows(self):
        df = _make_multi_month_candles()
        windows = build_month_windows({"SYM": df})
        assert len(windows) == 2
        assert windows[0][0] == "2025-01"
        assert windows[1][0] == "2025-02"


class TestBuildQuarterWindows:
    def test_empty_candles_returns_empty(self):
        empty = {
            "SYM": pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        }
        assert build_quarter_windows(empty) == []

    def test_q1_label_and_bounds(self):
        df = _make_flat_candles(3)  # Jan 2025 → Q1
        windows = build_quarter_windows({"SYM": df})
        assert len(windows) == 1
        label, start, end = windows[0]
        assert label == "Q1-2025"
        assert start == date(2025, 1, 1)
        assert end == date(2025, 3, 31)

    def test_two_months_in_same_quarter_gives_one_window(self):
        df = _make_multi_month_candles()  # Jan + Feb → both Q1-2025
        windows = build_quarter_windows({"SYM": df})
        assert len(windows) == 1
        assert windows[0][0] == "Q1-2025"


# ---------------------------------------------------------------------------
# TestCheckInsufficientEvidence
# ---------------------------------------------------------------------------


class TestCheckInsufficientEvidence:
    def test_trades_below_threshold_is_insufficient(self):
        row = {"trade_count": 50}
        assert check_insufficient_evidence(row) is True

    def test_trades_at_threshold_is_not_insufficient(self):
        row = {"trade_count": 100}
        assert check_insufficient_evidence(row) is False

    def test_none_trade_count_treated_as_zero(self):
        row = {"trade_count": None}
        assert check_insufficient_evidence(row) is True


# ---------------------------------------------------------------------------
# TestCheckStressRejection
# ---------------------------------------------------------------------------


class TestCheckStressRejection:
    def test_no_stress_rows_returns_no_rejection(self):
        rejected, reason = check_stress_rejection([])
        assert rejected is False
        assert reason is None

    def test_stress_above_threshold_not_rejected(self):
        rows = [
            {"slippage_label": "+1tick", "total_pnl": -200.0},
            {"slippage_label": "+2tick", "total_pnl": -400.0},
        ]
        rejected, _ = check_stress_rejection(rows, material_threshold=-500.0)
        assert rejected is False

    def test_stress_below_threshold_is_rejected(self):
        rows = [
            {"slippage_label": "+1tick", "total_pnl": -300.0},
            {"slippage_label": "+2tick", "total_pnl": -600.0},
        ]
        rejected, reason = check_stress_rejection(rows, material_threshold=-500.0)
        assert rejected is True
        assert "+2tick" in reason

    def test_rejection_reason_includes_slippage_label_and_net(self):
        rows = [{"slippage_label": "+1tick", "total_pnl": -999.0}]
        _, reason = check_stress_rejection(rows, material_threshold=-500.0)
        assert reason is not None
        assert "+1tick" in reason
        assert "-999" in reason


# ---------------------------------------------------------------------------
# TestRunExtendedValidation
# ---------------------------------------------------------------------------


class TestRunExtendedValidation:
    def _minimal_candles(self) -> dict[str, pd.DataFrame]:
        """Flat candles for both symbols — no trades triggered."""
        df = _make_flat_candles(3)
        return {"ICICIBANK": df.copy(), "TCS": df.copy()}

    def _single_window(self) -> list[tuple[str, str, date | None, date | None]]:
        return [("full", "full", None, None)]

    def test_result_count_equals_configs_times_windows_times_slippage(self):
        candles = self._minimal_candles()
        windows = self._single_window()
        results = run_extended_validation(
            SELECTED_CONFIGS,
            candles,
            windows,
            Decimal("100000"),
            10,
            "minute",
        )
        expected = len(SELECTED_CONFIGS) * len(windows) * len(SLIPPAGE_SCENARIOS)
        assert len(results) == expected

    def test_each_row_has_slippage_label(self):
        candles = self._minimal_candles()
        windows = self._single_window()
        results = run_extended_validation(
            SELECTED_CONFIGS,
            candles,
            windows,
            Decimal("100000"),
            10,
            "minute",
        )
        slip_labels = {r["slippage_label"] for r in results}
        assert slip_labels == {"base", "+1tick", "+2tick"}

    def test_no_trades_flags_insufficient_evidence(self):
        """Flat candles → no trades → trade_count=0 < 100 → insufficient_evidence=True."""
        candles = self._minimal_candles()
        windows = self._single_window()
        results = run_extended_validation(
            SELECTED_CONFIGS,
            candles,
            windows,
            Decimal("100000"),
            10,
            "minute",
        )
        for row in results:
            assert row["insufficient_evidence"] is True

    def test_missing_symbol_skipped(self):
        """If a symbol is not in candles, its config produces no results."""
        # Only TCS available
        df = _make_flat_candles(3)
        candles = {"TCS": df}
        windows = self._single_window()
        results = run_extended_validation(
            SELECTED_CONFIGS,
            candles,
            windows,
            Decimal("100000"),
            10,
            "minute",
        )
        # Only TCS_noRVOL config runs → 1 config × 1 window × 3 scenarios = 3 rows
        assert len(results) == 3
        assert all(r["config_label"] == "TCS_noRVOL" for r in results)


# ---------------------------------------------------------------------------
# TestNoLiveTradingImports
# ---------------------------------------------------------------------------


class TestNoLiveTradingImports:
    def test_no_zerodha_in_new_script(self):
        script_path = ROOT / "scripts" / "validate_selected_first_hour.py"
        source = script_path.read_text()
        assert "zerodha" not in source.lower()
        assert "kite" not in source.lower()

    def test_no_dotenv_in_new_script(self):
        script_path = ROOT / "scripts" / "validate_selected_first_hour.py"
        source = script_path.read_text()
        assert "load_dotenv" not in source
        assert "import dotenv" not in source
