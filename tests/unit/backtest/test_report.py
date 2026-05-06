"""Tests for BacktestReport."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from trading_engine.backtest.metrics import BacktestMetrics
from trading_engine.backtest.report import BacktestReport


def _empty_report() -> BacktestReport:
    return BacktestReport(
        strategy_id="test_strategy",
        symbols=["RELIANCE"],
        start_time=datetime(2024, 1, 15, 9, 15),
        end_time=datetime(2024, 1, 15, 15, 30),
        initial_cash=Decimal("100000"),
        final_equity=Decimal("101000"),
        metrics=BacktestMetrics(
            total_return=Decimal("0.01"),
            total_pnl=Decimal("1000"),
        ),
        fills=[],
        equity_curve=[],
        parameters={"interval": "minute"},
    )


class TestBacktestReportToDict:
    def test_to_dict_returns_dict(self) -> None:
        report = _empty_report()
        d = report.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_has_strategy_id(self) -> None:
        report = _empty_report()
        assert report.to_dict()["strategy_id"] == "test_strategy"

    def test_to_dict_has_symbols(self) -> None:
        report = _empty_report()
        assert report.to_dict()["symbols"] == ["RELIANCE"]

    def test_to_dict_cash_is_string(self) -> None:
        report = _empty_report()
        d = report.to_dict()
        assert isinstance(d["initial_cash"], str)
        assert isinstance(d["final_equity"], str)

    def test_to_dict_timestamps_are_strings(self) -> None:
        report = _empty_report()
        d = report.to_dict()
        assert isinstance(d["start_time"], str)
        assert isinstance(d["end_time"], str)

    def test_to_dict_metrics_present(self) -> None:
        report = _empty_report()
        d = report.to_dict()
        assert "metrics" in d
        assert "total_return" in d["metrics"]

    def test_to_dict_fills_is_list(self) -> None:
        report = _empty_report()
        assert isinstance(report.to_dict()["fills"], list)

    def test_to_dict_equity_curve_is_list(self) -> None:
        report = _empty_report()
        assert isinstance(report.to_dict()["equity_curve"], list)

    def test_to_dict_is_json_serialisable(self) -> None:
        report = _empty_report()
        d = report.to_dict()
        # Should not raise.
        json_str = json.dumps(d)
        assert len(json_str) > 0

    def test_to_dict_with_equity_curve(self) -> None:
        report = _empty_report()
        report.equity_curve.append((datetime(2024, 1, 15, 9, 15), Decimal("100000")))
        d = report.to_dict()
        assert len(d["equity_curve"]) == 1
        assert "timestamp" in d["equity_curve"][0]
        assert "equity" in d["equity_curve"][0]

    def test_to_dict_parameters_preserved(self) -> None:
        report = _empty_report()
        assert report.to_dict()["parameters"]["interval"] == "minute"

    def test_none_start_time_serialises(self) -> None:
        report = _empty_report()
        report.start_time = None
        d = report.to_dict()
        assert d["start_time"] is None


class TestBacktestReportSaveJson:
    def test_save_json_creates_file(self, tmp_path: Path) -> None:
        report = _empty_report()
        path = tmp_path / "report.json"
        report.save_json(path)
        assert path.exists()

    def test_save_json_creates_parent_dirs(self, tmp_path: Path) -> None:
        report = _empty_report()
        path = tmp_path / "reports" / "run1" / "report.json"
        report.save_json(path)
        assert path.exists()

    def test_save_json_valid_json(self, tmp_path: Path) -> None:
        report = _empty_report()
        path = tmp_path / "report.json"
        report.save_json(path)
        with open(path) as f:
            data = json.load(f)
        assert data["strategy_id"] == "test_strategy"

    def test_save_json_accepts_string_path(self, tmp_path: Path) -> None:
        report = _empty_report()
        path = str(tmp_path / "report.json")
        report.save_json(path)
        assert Path(path).exists()
