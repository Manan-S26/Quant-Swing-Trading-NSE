"""Tests for StrategyValidator."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trading_engine.backtest.metrics import BacktestMetrics
from trading_engine.backtest.report import BacktestReport
from trading_engine.validation.models import ValidationGateConfig
from trading_engine.validation.validator import StrategyValidator

_D = Decimal
_TS = datetime(2024, 1, 15, 9, 15)
_TS2 = datetime(2024, 1, 15, 15, 30)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _metrics(**kwargs) -> BacktestMetrics:
    defaults = dict(
        total_return=_D("0.05"),
        total_pnl=_D("5000"),
        realized_pnl=_D("5000"),
        unrealized_pnl=_D("0"),
        max_drawdown=_D("0.05"),
        win_rate=_D("0.6"),
        profit_factor=_D("2.0"),
        trade_count=50,
        winning_trades=30,
        losing_trades=20,
        average_win=_D("250"),
        average_loss=_D("125"),
        expectancy=_D("100"),
        total_fees=_D("200"),
        average_trade_pnl=_D("100"),
        best_trade_pnl=_D("500"),
        worst_trade_pnl=_D("-200"),
        sharpe_ratio=1.2,
        sortino_ratio=1.5,
        cagr=0.3,
    )
    defaults.update(kwargs)
    return BacktestMetrics(**defaults)


def _report(metrics: BacktestMetrics | None = None) -> BacktestReport:
    return BacktestReport(
        strategy_id="test",
        symbols=["RELIANCE"],
        start_time=_TS,
        end_time=_TS2,
        initial_cash=_D("100000"),
        final_equity=_D("105000"),
        metrics=metrics or _metrics(),
    )


# ---------------------------------------------------------------------------
# Tests: passes when all gates are met
# ---------------------------------------------------------------------------


class TestValidatorPasses:
    def test_empty_config_always_passes(self):
        validator = StrategyValidator(ValidationGateConfig(min_trades=0))
        result = validator.validate(_report())
        assert result.passed is True
        assert result.failed_gates == []

    def test_passes_all_gates(self):
        cfg = ValidationGateConfig(
            min_trades=30,
            min_sharpe=0.5,
            max_drawdown_pct=0.20,
            min_win_rate=0.4,
            min_profit_factor=1.0,
            min_expectancy=50.0,
        )
        result = StrategyValidator(cfg).validate(_report())
        assert result.passed is True

    def test_result_contains_metrics_snapshot(self):
        result = StrategyValidator(ValidationGateConfig(min_trades=0)).validate(_report())
        assert "trade_count" in result.metrics
        assert "sharpe_ratio" in result.metrics

    def test_to_dict_passed(self):
        result = StrategyValidator(ValidationGateConfig(min_trades=0)).validate(_report())
        d = result.to_dict()
        assert d["passed"] is True
        assert d["failed_gates"] == []


# ---------------------------------------------------------------------------
# Tests: min_trades gate
# ---------------------------------------------------------------------------


class TestMinTradesGate:
    def test_fails_when_below_min_trades(self):
        cfg = ValidationGateConfig(min_trades=100)
        result = StrategyValidator(cfg).validate(_report(_metrics(trade_count=5)))
        assert result.passed is False
        gate_names = [f.gate_name for f in result.failed_gates]
        assert "min_trades" in gate_names

    def test_passes_exactly_at_min_trades(self):
        cfg = ValidationGateConfig(min_trades=50)
        result = StrategyValidator(cfg).validate(_report(_metrics(trade_count=50)))
        assert result.passed is True

    def test_failure_message_mentions_count(self):
        cfg = ValidationGateConfig(min_trades=100)
        result = StrategyValidator(cfg).validate(_report(_metrics(trade_count=5)))
        failure = next(f for f in result.failed_gates if f.gate_name == "min_trades")
        assert "5" in failure.actual


# ---------------------------------------------------------------------------
# Tests: min_sharpe gate
# ---------------------------------------------------------------------------


class TestMinSharpeGate:
    def test_fails_when_sharpe_below_threshold(self):
        cfg = ValidationGateConfig(min_trades=0, min_sharpe=2.0)
        result = StrategyValidator(cfg).validate(_report(_metrics(sharpe_ratio=0.5)))
        assert result.passed is False
        assert any(f.gate_name == "min_sharpe" for f in result.failed_gates)

    def test_passes_when_sharpe_above_threshold(self):
        cfg = ValidationGateConfig(min_trades=0, min_sharpe=1.0)
        result = StrategyValidator(cfg).validate(_report(_metrics(sharpe_ratio=1.5)))
        assert result.passed is True

    def test_fails_when_sharpe_is_none(self):
        cfg = ValidationGateConfig(min_trades=0, min_sharpe=0.5)
        result = StrategyValidator(cfg).validate(_report(_metrics(sharpe_ratio=None)))
        assert result.passed is False
        failure = next(f for f in result.failed_gates if f.gate_name == "min_sharpe")
        assert "MISSING" in failure.actual

    def test_not_checked_when_config_is_none(self):
        cfg = ValidationGateConfig(min_trades=0, min_sharpe=None)
        result = StrategyValidator(cfg).validate(_report(_metrics(sharpe_ratio=None)))
        assert result.passed is True


# ---------------------------------------------------------------------------
# Tests: max_drawdown gate
# ---------------------------------------------------------------------------


class TestMaxDrawdownGate:
    def test_fails_when_drawdown_exceeds_limit(self):
        cfg = ValidationGateConfig(min_trades=0, max_drawdown_pct=0.10)
        result = StrategyValidator(cfg).validate(_report(_metrics(max_drawdown=_D("0.25"))))
        assert result.passed is False
        assert any(f.gate_name == "max_drawdown_pct" for f in result.failed_gates)

    def test_passes_when_drawdown_below_limit(self):
        cfg = ValidationGateConfig(min_trades=0, max_drawdown_pct=0.20)
        result = StrategyValidator(cfg).validate(_report(_metrics(max_drawdown=_D("0.05"))))
        assert result.passed is True

    def test_passes_exactly_at_limit(self):
        cfg = ValidationGateConfig(min_trades=0, max_drawdown_pct=0.20)
        result = StrategyValidator(cfg).validate(_report(_metrics(max_drawdown=_D("0.20"))))
        assert result.passed is True


# ---------------------------------------------------------------------------
# Tests: min_win_rate gate
# ---------------------------------------------------------------------------


class TestMinWinRateGate:
    def test_fails_when_win_rate_below_threshold(self):
        cfg = ValidationGateConfig(min_trades=0, min_win_rate=0.6)
        result = StrategyValidator(cfg).validate(_report(_metrics(win_rate=_D("0.3"))))
        assert result.passed is False

    def test_passes_when_win_rate_above_threshold(self):
        cfg = ValidationGateConfig(min_trades=0, min_win_rate=0.5)
        result = StrategyValidator(cfg).validate(_report(_metrics(win_rate=_D("0.6"))))
        assert result.passed is True


# ---------------------------------------------------------------------------
# Tests: min_profit_factor gate
# ---------------------------------------------------------------------------


class TestMinProfitFactorGate:
    def test_fails_when_profit_factor_below_threshold(self):
        cfg = ValidationGateConfig(min_trades=0, min_profit_factor=2.0)
        result = StrategyValidator(cfg).validate(_report(_metrics(profit_factor=_D("1.2"))))
        assert result.passed is False

    def test_passes_when_profit_factor_above_threshold(self):
        cfg = ValidationGateConfig(min_trades=0, min_profit_factor=1.5)
        result = StrategyValidator(cfg).validate(_report(_metrics(profit_factor=_D("2.0"))))
        assert result.passed is True


# ---------------------------------------------------------------------------
# Tests: min_expectancy gate
# ---------------------------------------------------------------------------


class TestMinExpectancyGate:
    def test_fails_when_expectancy_below_threshold(self):
        cfg = ValidationGateConfig(min_trades=0, min_expectancy=200.0)
        result = StrategyValidator(cfg).validate(_report(_metrics(expectancy=_D("50"))))
        assert result.passed is False

    def test_passes_when_expectancy_above_threshold(self):
        cfg = ValidationGateConfig(min_trades=0, min_expectancy=50.0)
        result = StrategyValidator(cfg).validate(_report(_metrics(expectancy=_D("100"))))
        assert result.passed is True


# ---------------------------------------------------------------------------
# Tests: max_total_fees_pct gate
# ---------------------------------------------------------------------------


class TestMaxFeesPctGate:
    def test_fails_when_fees_too_high(self):
        # fees=500, pnl=1000 → 50% > 20%
        cfg = ValidationGateConfig(min_trades=0, max_total_fees_pct_of_pnl=0.20)
        result = StrategyValidator(cfg).validate(
            _report(_metrics(total_fees=_D("500"), total_pnl=_D("1000")))
        )
        assert result.passed is False

    def test_passes_when_fees_acceptable(self):
        # fees=100, pnl=5000 → 2%
        cfg = ValidationGateConfig(min_trades=0, max_total_fees_pct_of_pnl=0.10)
        result = StrategyValidator(cfg).validate(
            _report(_metrics(total_fees=_D("100"), total_pnl=_D("5000")))
        )
        assert result.passed is True

    def test_fails_when_pnl_zero_and_fees_nonzero(self):
        cfg = ValidationGateConfig(min_trades=0, max_total_fees_pct_of_pnl=0.10)
        result = StrategyValidator(cfg).validate(
            _report(_metrics(total_fees=_D("100"), total_pnl=_D("0")))
        )
        assert result.passed is False


# ---------------------------------------------------------------------------
# Tests: multiple gates fail
# ---------------------------------------------------------------------------


class TestMultipleGateFailures:
    def test_all_gates_fail_collected(self):
        cfg = ValidationGateConfig(
            min_trades=100,
            min_sharpe=5.0,
            max_drawdown_pct=0.01,
            min_win_rate=0.9,
        )
        result = StrategyValidator(cfg).validate(_report())
        assert result.passed is False
        assert len(result.failed_gates) >= 3

    def test_independent_gate_pass_not_affected(self):
        # Only min_trades fails; other gates pass
        cfg = ValidationGateConfig(
            min_trades=100,
            min_sharpe=0.5,
            max_drawdown_pct=0.20,
        )
        result = StrategyValidator(cfg).validate(_report())
        gate_names = [f.gate_name for f in result.failed_gates]
        assert "min_trades" in gate_names
        assert "min_sharpe" not in gate_names
        assert "max_drawdown_pct" not in gate_names
