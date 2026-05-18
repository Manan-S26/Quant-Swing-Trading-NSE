"""Validation gate configuration and result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationGateConfig:
    """Configures the thresholds that a backtest must meet.

    All gate fields are optional.  Only gates that are not None are checked.

    Attributes:
        min_trades:              Minimum number of closed trades (SELL fills).
        min_sharpe:              Minimum annualised Sharpe ratio.
        max_drawdown_pct:        Maximum allowable max-drawdown fraction (0–1).
        min_win_rate:            Minimum win rate fraction (0–1).
        min_profit_factor:       Minimum profit factor (gross profit / gross loss).
        min_expectancy:          Minimum expected PnL per trade (in currency units).
        max_total_fees_pct_of_pnl: Max fees as a fraction of |total_pnl| (0–1).
    """

    min_trades: int = 30
    min_sharpe: float | None = None
    max_drawdown_pct: float | None = None
    min_win_rate: float | None = None
    min_profit_factor: float | None = None
    min_expectancy: float | None = None
    max_total_fees_pct_of_pnl: float | None = None

    def __post_init__(self) -> None:
        if self.min_trades < 0:
            raise ValueError(f"min_trades must be >= 0, got {self.min_trades}")
        if self.max_drawdown_pct is not None and not (0.0 <= self.max_drawdown_pct <= 1.0):
            raise ValueError(
                f"max_drawdown_pct must be between 0 and 1, got {self.max_drawdown_pct}"
            )
        if self.min_win_rate is not None and not (0.0 <= self.min_win_rate <= 1.0):
            raise ValueError(f"min_win_rate must be between 0 and 1, got {self.min_win_rate}")
        if self.min_profit_factor is not None and self.min_profit_factor <= 0:
            raise ValueError(f"min_profit_factor must be positive, got {self.min_profit_factor}")
        if self.max_total_fees_pct_of_pnl is not None and not (
            0.0 <= self.max_total_fees_pct_of_pnl <= 1.0
        ):
            raise ValueError(
                f"max_total_fees_pct_of_pnl must be between 0 and 1, "
                f"got {self.max_total_fees_pct_of_pnl}"
            )


@dataclass
class ValidationGateFailure:
    """Details of a single failed validation gate.

    Attributes:
        gate_name: Human-readable gate identifier.
        expected:  String description of the required threshold.
        actual:    String description of the observed metric value.
        message:   Full human-readable failure message.
    """

    gate_name: str
    expected: str
    actual: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "gate_name": self.gate_name,
            "expected": self.expected,
            "actual": self.actual,
            "message": self.message,
        }


@dataclass
class ValidationResult:
    """Result of running StrategyValidator.validate().

    Attributes:
        passed:       True when all configured gates are met.
        failed_gates: List of gate failures (empty when passed=True).
        metrics:      Snapshot of the key metrics evaluated (JSON-safe values).
    """

    passed: bool
    failed_gates: list[ValidationGateFailure] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "failed_gates": [f.to_dict() for f in self.failed_gates],
            "metrics": self.metrics,
        }
