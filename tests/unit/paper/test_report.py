"""Tests for PaperTradingReport."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from trading_engine.domain.enums import Exchange, RiskReasonCode, Side
from trading_engine.domain.identifiers import (
    generate_fill_id,
    generate_internal_order_id,
    generate_risk_decision_id,
)
from trading_engine.domain.models import RiskDecision, TradeFill
from trading_engine.paper.report import PaperTradingReport

_TS = datetime(2024, 1, 15, 9, 30)


def _make_fill() -> TradeFill:
    return TradeFill(
        fill_id=generate_fill_id(),
        internal_order_id=generate_internal_order_id(),
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        side=Side.BUY,
        quantity=10,
        price=Decimal("100"),
        fees=Decimal("20"),
        timestamp=_TS,
    )


def _make_decision(approved: bool = False) -> RiskDecision:
    return RiskDecision(
        risk_decision_id=generate_risk_decision_id(),
        approved=approved,
        reason_code=RiskReasonCode.KILL_SWITCH_ACTIVE,
        reason_message="Kill switch active.",
        timestamp=_TS,
    )


def _make_report(**kwargs) -> PaperTradingReport:
    defaults = {
        "strategy_id": "test_strategy",
        "symbols": ["RELIANCE"],
        "start_time": _TS,
        "end_time": _TS,
        "initial_cash": Decimal("100000"),
        "final_equity": Decimal("101000"),
    }
    defaults.update(kwargs)
    return PaperTradingReport(**defaults)


class TestToDict:
    def test_contains_required_keys(self):
        report = _make_report()
        d = report.to_dict()
        expected_keys = {
            "strategy_id",
            "symbols",
            "start_time",
            "end_time",
            "initial_cash",
            "final_equity",
            "fills",
            "rejected_risk_decisions",
            "equity_curve",
            "parameters",
        }
        assert expected_keys == set(d.keys())

    def test_decimals_serialised_as_strings(self):
        report = _make_report(initial_cash=Decimal("12345.67"), final_equity=Decimal("12500.00"))
        d = report.to_dict()
        assert d["initial_cash"] == "12345.67"
        assert d["final_equity"] == "12500.00"

    def test_datetimes_serialised_as_isoformat(self):
        ts = datetime(2024, 1, 15, 9, 30, 0)
        report = _make_report(start_time=ts, end_time=ts)
        d = report.to_dict()
        assert d["start_time"] == "2024-01-15T09:30:00"
        assert d["end_time"] == "2024-01-15T09:30:00"

    def test_none_timestamps_serialised_as_null(self):
        report = _make_report(start_time=None, end_time=None)
        d = report.to_dict()
        assert d["start_time"] is None
        assert d["end_time"] is None

    def test_fills_serialised(self):
        report = _make_report(fills=[_make_fill()])
        d = report.to_dict()
        assert len(d["fills"]) == 1
        fill_dict = d["fills"][0]
        assert "fill_id" in fill_dict
        assert fill_dict["symbol"] == "RELIANCE"
        assert fill_dict["quantity"] == 10
        assert fill_dict["price"] == "100"
        assert fill_dict["fees"] == "20"

    def test_rejected_risk_decisions_serialised(self):
        report = _make_report(rejected_risk_decisions=[_make_decision()])
        d = report.to_dict()
        assert len(d["rejected_risk_decisions"]) == 1
        entry = d["rejected_risk_decisions"][0]
        assert entry["approved"] is False
        assert "risk_decision_id" in entry
        assert "reason_code" in entry
        assert "timestamp" in entry

    def test_equity_curve_serialised(self):
        curve = [(datetime(2024, 1, 15, 9, 30), Decimal("100000"))]
        report = _make_report(equity_curve=curve)
        d = report.to_dict()
        assert len(d["equity_curve"]) == 1
        assert d["equity_curve"][0]["equity"] == "100000"

    def test_empty_collections(self):
        report = _make_report()
        d = report.to_dict()
        assert d["fills"] == []
        assert d["rejected_risk_decisions"] == []
        assert d["equity_curve"] == []
        assert d["parameters"] == {}


class TestSaveJson:
    def test_save_json_creates_file(self, tmp_path):
        report = _make_report()
        path = tmp_path / "report.json"
        report.save_json(path)
        assert path.exists()

    def test_save_json_valid_json(self, tmp_path):
        report = _make_report(fills=[_make_fill()])
        path = tmp_path / "report.json"
        report.save_json(path)
        with open(path) as f:
            data = json.load(f)
        assert data["strategy_id"] == "test_strategy"

    def test_save_json_creates_parent_dirs(self, tmp_path):
        report = _make_report()
        path = tmp_path / "nested" / "dir" / "report.json"
        report.save_json(path)
        assert path.exists()

    def test_save_json_includes_rejected_decisions(self, tmp_path):
        report = _make_report(rejected_risk_decisions=[_make_decision()])
        path = tmp_path / "report.json"
        report.save_json(path)
        with open(path) as f:
            data = json.load(f)
        assert len(data["rejected_risk_decisions"]) == 1

    def test_save_json_accepts_string_path(self, tmp_path):
        report = _make_report()
        path = str(tmp_path / "report.json")
        report.save_json(path)
        with open(path) as f:
            data = json.load(f)
        assert "strategy_id" in data
