"""Paper trading report.

Collects paper trading results and serialises to JSON.
No metrics (unlike BacktestReport) — paper mode is forward-only, not evaluated.

No Zerodha imports. No real orders.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading_engine.domain.models import RiskDecision, TradeFill


def _json_default(obj: Any) -> Any:
    """Custom JSON serialiser for Decimal and datetime."""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


@dataclass
class PaperTradingReport:
    """Full results of a paper trading run.

    Fields:
        strategy_id:              Identifier of the strategy that was run.
        symbols:                  List of symbols traded.
        start_time:               First bar timestamp.
        end_time:                 Last bar timestamp.
        initial_cash:             Starting portfolio cash.
        final_equity:             Ending portfolio equity.
        fills:                    All TradeFill objects recorded.
        rejected_risk_decisions:  RiskDecisions that blocked order intents.
        equity_curve:             List of (timestamp, equity) pairs.
        parameters:               Arbitrary strategy / run parameters.
    """

    strategy_id: str
    symbols: list[str]
    start_time: datetime | None
    end_time: datetime | None
    initial_cash: Decimal
    final_equity: Decimal
    fills: list[TradeFill] = field(default_factory=list)
    rejected_risk_decisions: list[RiskDecision] = field(default_factory=list)
    equity_curve: list[tuple[datetime, Decimal]] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "strategy_id": self.strategy_id,
            "symbols": self.symbols,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "initial_cash": str(self.initial_cash),
            "final_equity": str(self.final_equity),
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
            "equity_curve": [
                {"timestamp": ts.isoformat(), "equity": str(eq)} for ts, eq in self.equity_curve
            ],
            "parameters": self.parameters,
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
