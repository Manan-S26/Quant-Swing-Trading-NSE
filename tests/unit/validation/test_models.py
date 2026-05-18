"""Tests for ValidationGateConfig, ValidationGateFailure, ValidationResult."""

from __future__ import annotations

import pytest

from trading_engine.validation.models import (
    ValidationGateConfig,
    ValidationGateFailure,
    ValidationResult,
)


class TestValidationGateConfig:
    def test_default_min_trades(self):
        cfg = ValidationGateConfig()
        assert cfg.min_trades == 30

    def test_all_optional_fields_default_none(self):
        cfg = ValidationGateConfig()
        for attr in (
            "min_sharpe",
            "max_drawdown_pct",
            "min_win_rate",
            "min_profit_factor",
            "min_expectancy",
            "max_total_fees_pct_of_pnl",
        ):
            assert getattr(cfg, attr) is None

    def test_min_trades_negative_raises(self):
        with pytest.raises(ValueError, match="min_trades"):
            ValidationGateConfig(min_trades=-1)

    def test_min_trades_zero_allowed(self):
        cfg = ValidationGateConfig(min_trades=0)
        assert cfg.min_trades == 0

    def test_max_drawdown_pct_out_of_range_raises(self):
        with pytest.raises(ValueError, match="max_drawdown_pct"):
            ValidationGateConfig(max_drawdown_pct=1.5)

    def test_max_drawdown_pct_negative_raises(self):
        with pytest.raises(ValueError):
            ValidationGateConfig(max_drawdown_pct=-0.1)

    def test_max_drawdown_pct_zero_allowed(self):
        cfg = ValidationGateConfig(max_drawdown_pct=0.0)
        assert cfg.max_drawdown_pct == 0.0

    def test_min_win_rate_out_of_range_raises(self):
        with pytest.raises(ValueError, match="min_win_rate"):
            ValidationGateConfig(min_win_rate=1.1)

    def test_min_win_rate_valid(self):
        cfg = ValidationGateConfig(min_win_rate=0.5)
        assert cfg.min_win_rate == 0.5

    def test_min_profit_factor_zero_raises(self):
        with pytest.raises(ValueError, match="min_profit_factor"):
            ValidationGateConfig(min_profit_factor=0.0)

    def test_min_profit_factor_negative_raises(self):
        with pytest.raises(ValueError):
            ValidationGateConfig(min_profit_factor=-1.0)

    def test_min_profit_factor_positive_valid(self):
        cfg = ValidationGateConfig(min_profit_factor=1.5)
        assert cfg.min_profit_factor == 1.5

    def test_max_total_fees_pct_out_of_range_raises(self):
        with pytest.raises(ValueError, match="max_total_fees_pct_of_pnl"):
            ValidationGateConfig(max_total_fees_pct_of_pnl=2.0)

    def test_custom_config(self):
        cfg = ValidationGateConfig(
            min_trades=50,
            min_sharpe=0.8,
            max_drawdown_pct=0.15,
            min_win_rate=0.45,
            min_profit_factor=1.2,
            min_expectancy=100.0,
        )
        assert cfg.min_trades == 50
        assert cfg.min_sharpe == 0.8


class TestValidationGateFailure:
    def test_to_dict(self):
        failure = ValidationGateFailure(
            gate_name="min_trades",
            expected=">= 30",
            actual="5",
            message="Not enough trades.",
        )
        d = failure.to_dict()
        assert d["gate_name"] == "min_trades"
        assert d["expected"] == ">= 30"
        assert d["actual"] == "5"
        assert d["message"] == "Not enough trades."

    def test_to_dict_all_keys_present(self):
        f = ValidationGateFailure(gate_name="x", expected="a", actual="b", message="c")
        assert set(f.to_dict().keys()) == {"gate_name", "expected", "actual", "message"}


class TestValidationResult:
    def test_passed_true_no_failures(self):
        result = ValidationResult(passed=True)
        assert result.passed is True
        assert result.failed_gates == []

    def test_passed_false_with_failures(self):
        f = ValidationGateFailure(gate_name="g", expected="e", actual="a", message="m")
        result = ValidationResult(passed=False, failed_gates=[f])
        assert result.passed is False

    def test_to_dict_passed(self):
        result = ValidationResult(passed=True, metrics={"trade_count": 50})
        d = result.to_dict()
        assert d["passed"] is True
        assert d["failed_gates"] == []
        assert d["metrics"]["trade_count"] == 50

    def test_to_dict_with_failures(self):
        f = ValidationGateFailure(gate_name="min_trades", expected=">= 30", actual="5", message="m")
        result = ValidationResult(passed=False, failed_gates=[f])
        d = result.to_dict()
        assert d["passed"] is False
        assert len(d["failed_gates"]) == 1
        assert d["failed_gates"][0]["gate_name"] == "min_trades"

    def test_to_dict_is_json_safe(self):
        import json

        result = ValidationResult(passed=True, metrics={"sharpe_ratio": 1.5, "trade_count": 30})
        json.dumps(result.to_dict())  # must not raise
