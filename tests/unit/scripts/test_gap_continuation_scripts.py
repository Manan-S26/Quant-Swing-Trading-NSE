"""Tests for sweep_gap_continuation_params.py."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from sweep_gap_continuation_params import build_grid, load_candles, PARAM_GRID  # noqa: E402


class TestBuildGrid:
    def test_returns_list_of_dicts(self):
        combos = build_grid()
        assert isinstance(combos, list)
        assert all(isinstance(c, dict) for c in combos)

    def test_full_grid_count(self):
        # 4 * 3 * 3 * 3 = 108 combinations
        combos = build_grid()
        expected = 4 * 3 * 3 * 3
        assert len(combos) == expected

    def test_max_combinations_limits(self):
        combos = build_grid(max_combinations=10)
        assert len(combos) == 10

    def test_each_combo_has_required_keys(self):
        combos = build_grid(max_combinations=1)
        required = {"min_gap_bps", "max_gap_bps", "continuation_trigger_bps", "stop_loss_bps"}
        assert required.issubset(combos[0].keys())

    def test_custom_grid(self):
        grid = {"min_gap_bps": [50, 100], "stop_loss_bps": [80, 120]}
        combos = build_grid(grid=grid)
        assert len(combos) == 4


class TestLoadCandles:
    def test_missing_symbol_skipped(self, tmp_path):
        candles = load_candles(["NONEXISTENT"], tmp_path, "minute")
        assert "NONEXISTENT" not in candles

    def test_loads_existing_parquet(self, tmp_path):
        sym_dir = tmp_path / "candles" / "NSE" / "FAKE"
        sym_dir.mkdir(parents=True)
        df = pd.DataFrame({
            "timestamp": [pd.Timestamp("2024-01-15 09:15:00")],
            "open": [100.0], "high": [101.0], "low": [99.0],
            "close": [100.5], "volume": [1000],
        })
        df.to_parquet(sym_dir / "minute.parquet")
        candles = load_candles(["FAKE"], tmp_path, "minute")
        assert "FAKE" in candles
        assert len(candles["FAKE"]) == 1


class TestNoLiveTradingInScripts:
    def test_no_zerodha_in_sweep_script(self):
        source = (ROOT / "scripts" / "sweep_gap_continuation_params.py").read_text()
        assert "zerodha" not in source.lower()
        assert "kite" not in source.lower()

    def test_no_dotenv_in_sweep_script(self):
        source = (ROOT / "scripts" / "sweep_gap_continuation_params.py").read_text()
        assert "load_dotenv" not in source
        assert "import dotenv" not in source
