"""Dry-run order preview.

DryRunExecutor shows what would happen if an OrderIntent were executed:
  - Runs the risk engine (if provided).
  - Creates an approval request (if approval gate is provided).
  - Returns a JSON-serialisable preview.

No orders are placed. No broker is called. No Zerodha APIs are invoked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from trading_engine.domain.enums import OrderType, ProductType, Side
from trading_engine.live_execution.models import ApprovalStatus

if TYPE_CHECKING:
    from trading_engine.domain.models import PortfolioSnapshot
    from trading_engine.live_execution.approvals import LiveOrderApprovalGate
    from trading_engine.risk.engine import RiskEngine
    from trading_engine.strategy.signals import OrderIntent

_ZERO = Decimal("0")


@dataclass
class DryRunOrderPreview:
    """What would happen if this OrderIntent were executed.

    Fields:
        generated_at:          When this preview was created.
        strategy_id:           Source strategy.
        symbol:                Trading symbol.
        side:                  BUY or SELL.
        quantity:              Number of shares.
        order_type:            MARKET, LIMIT, SL, or SL-M.
        product:               MIS, CNC, or NRML.
        estimated_price:       Indicative price (e.g. from last tick).
        estimated_order_value: quantity × estimated_price (if both available).
        risk_decision:         Risk engine result (None if no engine provided).
        approval_status:       Approval outcome (None if no gate provided).
        message:               Human-readable summary.
    """

    generated_at: datetime
    strategy_id: str
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType
    product: ProductType
    estimated_price: Decimal | None
    estimated_order_value: Decimal | None
    risk_decision: Any | None  # RiskDecision | None — avoid heavy import
    approval_status: ApprovalStatus | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict."""
        risk = None
        if self.risk_decision is not None:
            risk = {
                "approved": self.risk_decision.approved,
                "reason_code": str(self.risk_decision.reason_code),
                "reason_message": self.risk_decision.reason_message,
            }
        return {
            "generated_at": self.generated_at.isoformat(),
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "side": str(self.side),
            "quantity": self.quantity,
            "order_type": str(self.order_type),
            "product": str(self.product),
            "estimated_price": str(self.estimated_price) if self.estimated_price else None,
            "estimated_order_value": (
                str(self.estimated_order_value) if self.estimated_order_value else None
            ),
            "risk_decision": risk,
            "approval_status": str(self.approval_status) if self.approval_status else None,
            "message": self.message,
        }


class DryRunExecutor:
    """Preview the outcome of an OrderIntent without executing anything.

    Args:
        risk_engine:    Optional risk engine to run pre-trade checks.
        approval_gate:  Optional approval gate to show what would happen.

    Usage:
        executor = DryRunExecutor(risk_engine=my_risk_engine)
        preview = executor.preview(intent, portfolio_snapshot=snapshot, estimated_price=Decimal("2345"))
        print(json.dumps(preview.to_dict(), indent=2))
    """

    def __init__(
        self,
        risk_engine: RiskEngine | None = None,
        approval_gate: LiveOrderApprovalGate | None = None,
    ) -> None:
        self._risk_engine = risk_engine
        self._approval_gate = approval_gate

    def preview(
        self,
        order_intent: OrderIntent,
        portfolio_snapshot: PortfolioSnapshot | None = None,
        estimated_price: Decimal | None = None,
    ) -> DryRunOrderPreview:
        """Simulate processing an OrderIntent and return the result preview.

        No orders are placed. No broker is called.

        Steps:
          1. Run risk check (if risk_engine provided and snapshot available).
          2. If risk rejects, approval is AUTO_REJECTED; stop.
          3. Otherwise, query approval gate if provided.
          4. Return preview.
        """
        now = datetime.now(tz=UTC)
        side = Side(order_intent.side)
        order_type = OrderType(order_intent.order_type)
        product = ProductType(order_intent.product)

        # Compute estimated order value.
        est_value: Decimal | None = None
        if estimated_price is not None and estimated_price > _ZERO:
            est_value = estimated_price * Decimal(str(order_intent.quantity))

        # --- Risk check ---
        risk_decision: Any | None = None
        if self._risk_engine is not None and portfolio_snapshot is not None:
            risk_decision = self._risk_engine.check_order_intent(
                order_intent, portfolio_snapshot, now
            )

        # If risk rejected, don't proceed to approval.
        if risk_decision is not None and not risk_decision.approved:
            return DryRunOrderPreview(
                generated_at=now,
                strategy_id=order_intent.strategy_id,
                symbol=order_intent.symbol,
                side=side,
                quantity=order_intent.quantity,
                order_type=order_type,
                product=product,
                estimated_price=estimated_price,
                estimated_order_value=est_value,
                risk_decision=risk_decision,
                approval_status=ApprovalStatus.AUTO_REJECTED,
                message=(
                    f"DRY RUN: order would be BLOCKED by risk engine — "
                    f"{risk_decision.reason_code}: {risk_decision.reason_message}"
                ),
            )

        # --- Approval gate ---
        approval_status: ApprovalStatus | None = None
        if self._approval_gate is not None:
            from trading_engine.common.exceptions import ManualApprovalRequired

            try:
                decision = self._approval_gate.require_approval(
                    order_intent,
                    estimated_price=estimated_price,
                    reason="dry_run_preview",
                )
                approval_status = decision.status
            except ManualApprovalRequired:
                approval_status = ApprovalStatus.PENDING
            except Exception as exc:  # SafetyError etc.
                approval_status = ApprovalStatus.AUTO_REJECTED
                return DryRunOrderPreview(
                    generated_at=now,
                    strategy_id=order_intent.strategy_id,
                    symbol=order_intent.symbol,
                    side=side,
                    quantity=order_intent.quantity,
                    order_type=order_type,
                    product=product,
                    estimated_price=estimated_price,
                    estimated_order_value=est_value,
                    risk_decision=risk_decision,
                    approval_status=approval_status,
                    message=f"DRY RUN: approval gate blocked — {exc}",
                )

        # Build summary message.
        risk_ok = risk_decision is None or risk_decision.approved
        if approval_status == ApprovalStatus.APPROVED:
            approval_msg = "approval gate: APPROVED"
        elif approval_status == ApprovalStatus.PENDING:
            approval_msg = "approval gate: PENDING (awaiting operator)"
        elif approval_status is None:
            approval_msg = "no approval gate"
        else:
            approval_msg = f"approval gate: {approval_status}"

        msg = (
            f"DRY RUN: {side} {order_intent.quantity} {order_intent.symbol} "
            f"@ {estimated_price or 'MARKET'} — "
            f"risk: {'PASS' if risk_ok else 'FAIL'}, {approval_msg}. "
            "No order placed."
        )

        return DryRunOrderPreview(
            generated_at=now,
            strategy_id=order_intent.strategy_id,
            symbol=order_intent.symbol,
            side=side,
            quantity=order_intent.quantity,
            order_type=order_type,
            product=product,
            estimated_price=estimated_price,
            estimated_order_value=est_value,
            risk_decision=risk_decision,
            approval_status=approval_status,
            message=msg,
        )
