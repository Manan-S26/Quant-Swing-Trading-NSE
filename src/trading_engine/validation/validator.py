"""Strategy validator — checks BacktestReport against configured gates."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from trading_engine.validation.models import (
    ValidationGateConfig,
    ValidationGateFailure,
    ValidationResult,
)

if TYPE_CHECKING:
    from trading_engine.backtest.report import BacktestReport

_MISSING = "MISSING"


class StrategyValidator:
    """Checks a BacktestReport against ValidationGateConfig thresholds.

    Usage::

        config = ValidationGateConfig(min_trades=30, min_sharpe=0.5)
        validator = StrategyValidator(config)
        result = validator.validate(report)
        if not result.passed:
            for f in result.failed_gates:
                print(f.message)
    """

    def __init__(self, config: ValidationGateConfig) -> None:
        self._config = config

    def validate(self, report: BacktestReport) -> ValidationResult:
        """Evaluate the report against all configured gates.

        Args:
            report: A completed BacktestReport.

        Returns:
            ValidationResult with passed flag and any gate failures.
        """
        m = report.metrics
        failures: list[ValidationGateFailure] = []

        # Snapshot of evaluated metrics for the result dict (JSON-safe)
        metrics_snapshot: dict[str, Any] = {
            "trade_count": m.trade_count,
            "sharpe_ratio": m.sharpe_ratio,
            "max_drawdown": str(m.max_drawdown),
            "win_rate": str(m.win_rate),
            "profit_factor": str(m.profit_factor),
            "expectancy": str(m.expectancy),
            "total_fees": str(m.total_fees),
            "total_pnl": str(m.total_pnl),
        }

        cfg = self._config

        # --- Gate: min_trades ---
        if m.trade_count < cfg.min_trades:
            failures.append(
                ValidationGateFailure(
                    gate_name="min_trades",
                    expected=f">= {cfg.min_trades}",
                    actual=str(m.trade_count),
                    message=(f"Trade count {m.trade_count} is below minimum {cfg.min_trades}."),
                )
            )

        # --- Gate: min_sharpe ---
        if cfg.min_sharpe is not None:
            sharpe = m.sharpe_ratio
            if sharpe is None:
                failures.append(
                    ValidationGateFailure(
                        gate_name="min_sharpe",
                        expected=f">= {cfg.min_sharpe}",
                        actual=_MISSING,
                        message=(
                            f"Sharpe ratio could not be computed "
                            f"(insufficient data); required >= {cfg.min_sharpe}."
                        ),
                    )
                )
            elif sharpe < cfg.min_sharpe:
                failures.append(
                    ValidationGateFailure(
                        gate_name="min_sharpe",
                        expected=f">= {cfg.min_sharpe}",
                        actual=f"{sharpe:.4f}",
                        message=f"Sharpe ratio {sharpe:.4f} is below minimum {cfg.min_sharpe}.",
                    )
                )

        # --- Gate: max_drawdown_pct ---
        if cfg.max_drawdown_pct is not None:
            dd = float(m.max_drawdown)
            if dd > cfg.max_drawdown_pct:
                failures.append(
                    ValidationGateFailure(
                        gate_name="max_drawdown_pct",
                        expected=f"<= {cfg.max_drawdown_pct:.1%}",
                        actual=f"{dd:.1%}",
                        message=(
                            f"Max drawdown {dd:.1%} exceeds limit {cfg.max_drawdown_pct:.1%}."
                        ),
                    )
                )

        # --- Gate: min_win_rate ---
        if cfg.min_win_rate is not None:
            wr = float(m.win_rate)
            if wr < cfg.min_win_rate:
                failures.append(
                    ValidationGateFailure(
                        gate_name="min_win_rate",
                        expected=f">= {cfg.min_win_rate:.1%}",
                        actual=f"{wr:.1%}",
                        message=f"Win rate {wr:.1%} is below minimum {cfg.min_win_rate:.1%}.",
                    )
                )

        # --- Gate: min_profit_factor ---
        if cfg.min_profit_factor is not None:
            pf = float(m.profit_factor)
            if pf < cfg.min_profit_factor:
                failures.append(
                    ValidationGateFailure(
                        gate_name="min_profit_factor",
                        expected=f">= {cfg.min_profit_factor}",
                        actual=f"{pf:.4f}",
                        message=(
                            f"Profit factor {pf:.4f} is below minimum {cfg.min_profit_factor}."
                        ),
                    )
                )

        # --- Gate: min_expectancy ---
        if cfg.min_expectancy is not None:
            exp = float(m.expectancy)
            if exp < cfg.min_expectancy:
                failures.append(
                    ValidationGateFailure(
                        gate_name="min_expectancy",
                        expected=f">= {cfg.min_expectancy}",
                        actual=f"{exp:.4f}",
                        message=(f"Expectancy {exp:.4f} is below minimum {cfg.min_expectancy}."),
                    )
                )

        # --- Gate: max_total_fees_pct_of_pnl ---
        if cfg.max_total_fees_pct_of_pnl is not None:
            total_pnl = m.total_pnl
            if total_pnl == Decimal("0"):
                # Zero PnL — fees are technically infinite fraction; fail if fees > 0
                if m.total_fees > Decimal("0"):
                    failures.append(
                        ValidationGateFailure(
                            gate_name="max_total_fees_pct_of_pnl",
                            expected=f"<= {cfg.max_total_fees_pct_of_pnl:.1%} of PnL",
                            actual="N/A (PnL is zero)",
                            message=(
                                "Cannot compute fees/PnL ratio: total_pnl is zero "
                                "but fees are non-zero."
                            ),
                        )
                    )
            else:
                fees_pct = float(m.total_fees) / abs(float(total_pnl))
                if fees_pct > cfg.max_total_fees_pct_of_pnl:
                    failures.append(
                        ValidationGateFailure(
                            gate_name="max_total_fees_pct_of_pnl",
                            expected=f"<= {cfg.max_total_fees_pct_of_pnl:.1%}",
                            actual=f"{fees_pct:.1%}",
                            message=(
                                f"Total fees are {fees_pct:.1%} of |PnL|, "
                                f"exceeding limit of {cfg.max_total_fees_pct_of_pnl:.1%}."
                            ),
                        )
                    )

        return ValidationResult(
            passed=len(failures) == 0,
            failed_gates=failures,
            metrics=metrics_snapshot,
        )
