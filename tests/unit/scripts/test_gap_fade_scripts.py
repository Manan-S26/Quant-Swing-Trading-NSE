"""Unit tests for sweep_gap_fade_params.py CLI functions."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from sweep_gap_fade_params import (  # noqa: E402
    PARAM_GRID,
    build_grid,
    load_candles,
)


class TestBuildGrid:
    def test_default_grid_has_correct_total(self):
        """Default grid: 4*3*3*3*3 = 324 combos."""
        combos = build_grid()
        assert len(combos) == 324

    def test_max_combinations_limits_output(self):
        combos = build_grid(max_combinations=50)
        assert len(combos) == 50

    def test_each_combo_has_all_param_keys(self):
        keys = set(PARAM_GRID.keys())
        for combo in build_grid(max_combinations=5):
            assert set(combo.keys()) == keys

    def test_custom_grid_overrides_default(self):
        custom = {"min_gap_bps": [60, 80], "stop_loss_bps": [80]}
        combos = build_grid(grid=custom)
        assert len(combos) == 2

    def test_max_combinations_none_returns_all(self):
        combos = build_grid(max_combinations=None)
        assert len(combos) == 324


class TestLoadCandles:
    def test_missing_symbol_skipped(self, tmp_path):
        candles = load_candles(["NONEXISTENT"], tmp_path, "minute")
        assert candles == {}

    def test_parquet_loaded_correctly(self, tmp_path):
        symbol = "TESTX"
        data_path = tmp_path / "candles" / "NSE" / symbol
        data_path.mkdir(parents=True)
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2024-01-15 09:15", periods=5, freq="1min"),
                "open": [100.0] * 5,
                "high": [101.0] * 5,
                "low": [99.0] * 5,
                "close": [100.0] * 5,
                "volume": [1000] * 5,
            }
        )
        df.to_parquet(data_path / "minute.parquet")
        candles = load_candles([symbol], tmp_path, "minute")
        assert symbol in candles
        assert len(candles[symbol]) == 5


class TestNoLiveTradingInScripts:
    def test_no_zerodha_in_sweep_script(self):
        source = (ROOT / "scripts" / "sweep_gap_fade_params.py").read_text()
        assert "zerodha" not in source.lower()
        assert "kite" not in source.lower()

    def test_no_dotenv_in_run_script(self):
        source = (ROOT / "scripts" / "run_gap_fade_backtest.py").read_text()
        assert "load_dotenv" not in source
        assert "import dotenv" not in source
