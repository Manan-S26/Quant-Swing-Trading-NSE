"""Backtest report — collects results and serialises to JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from trading_engine.backtest.metrics import BacktestMetrics
from trading_engine.domain.models import RiskDecision, TradeFill

if TYPE_CHECKING:
    pass


def _json_default(obj: Any) -> Any:
    """Custom JSON serialiser for Decimal and datetime."""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


@dataclass
class BacktestReport:
    """Full results of a completed backtest run.

    Fields:
        strategy_id:       Identifier of the strategy that was run.
        symbols:           List of symbols traded.
        start_time:        First bar timestamp.
        end_time:          Last bar timestamp.
        initial_cash:      Starting portfolio cash.
        final_equity:      Ending portfolio equity.
        metrics:           BacktestMetrics summary.
        fills:             All TradeFill objects recorded.
        equity_curve:      List of (timestamp, equity) pairs.
        parameters:        Arbitrary strategy / run parameters for reproducibility.
        rejected_risk_decisions: Risk-rejected decisions recorded during the run.
        validation_result: Optional StrategyValidator result attached after the run.
    """

    strategy_id: str
    symbols: list[str]
    start_time: datetime | None
    end_time: datetime | None
    initial_cash: Decimal
    final_equity: Decimal
    metrics: BacktestMetrics
    fills: list[TradeFill] = field(default_factory=list)
    equity_curve: list[tuple[datetime, Decimal]] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    rejected_risk_decisions: list[RiskDecision] = field(default_factory=list)
    validation_result: Any | None = None  # ValidationResult | None (avoid circular import)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "strategy_id": self.strategy_id,
            "symbols": self.symbols,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "initial_cash": str(self.initial_cash),
            "final_equity": str(self.final_equity),
            "metrics": {
                "total_return": str(self.metrics.total_return),
                "total_pnl": str(self.metrics.total_pnl),
                "realized_pnl": str(self.metrics.realized_pnl),
                "unrealized_pnl": str(self.metrics.unrealized_pnl),
                "max_drawdown": str(self.metrics.max_drawdown),
                "win_rate": str(self.metrics.win_rate),
                "profit_factor": str(self.metrics.profit_factor),
                "trade_count": self.metrics.trade_count,
                "winning_trades": self.metrics.winning_trades,
                "losing_trades": self.metrics.losing_trades,
                "average_win": str(self.metrics.average_win),
                "average_loss": str(self.metrics.average_loss),
                "expectancy": str(self.metrics.expectancy),
                "total_fees": str(self.metrics.total_fees),
                # New Milestone 13 fields
                "average_trade_pnl": str(self.metrics.average_trade_pnl),
                "best_trade_pnl": str(self.metrics.best_trade_pnl),
                "worst_trade_pnl": str(self.metrics.worst_trade_pnl),
                "sharpe_ratio": self.metrics.sharpe_ratio,
                "sortino_ratio": self.metrics.sortino_ratio,
                "cagr": self.metrics.cagr,
            },
            "fills": [
                {
                    "fill_id": f.fill_id,
                    "symbol": f.symbol,
                    "side": str(f.side),
                    "quantity": f.quantity,
                    "price": str(f.price),
                    "fees": str(f.fees),
                    "timestamp": f.timestamp.isoformat(),
                }
                for f in self.fills
            ],
            "equity_curve": [
                {"timestamp": ts.isoformat(), "equity": str(eq)} for ts, eq in self.equity_curve
            ],
            "parameters": self.parameters,
            "rejected_risk_decisions": [
                {
                    "risk_decision_id": d.risk_decision_id,
                    "approved": d.approved,
                    "reason_code": str(d.reason_code),
                    "reason_message": d.reason_message,
                    "timestamp": d.timestamp.isoformat(),
                }
                for d in self.rejected_risk_decisions
            ],
            "validation_result": (
                self.validation_result.to_dict() if self.validation_result is not None else None
            ),
        }

    def save_json(self, path: str | Path) -> None:
        """Write the report to a JSON file.

        Args:
            path: Destination file path. Parent directories are created.
        """
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, default=_json_default)
