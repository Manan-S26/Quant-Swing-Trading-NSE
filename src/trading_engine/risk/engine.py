"""Risk engine — pre-trade checks for every OrderIntent.

Sits between strategy output and simulated/live order execution.
Returns a RiskDecision for every intent; rejected intents must not execute.

No Zerodha imports.  No order placement.  Reusable for backtest, paper, and
live modes — callers are responsible for supplying the correct portfolio
snapshot and timestamp.

Check order (first failing check wins):
  1. Kill switch active
  2. Symbol not in allowed_symbols
  3. Product type not in allowed_product_types
  4. Order type not in allowed_order_types
  5. Order value > max_order_value
  6. Open position count > max_open_positions
  7. Daily loss > max_daily_loss
  8. Trades today > max_trades_per_day
  9. Orders this second > max_orders_per_second
 10. Approve
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from decimal import Decimal

from trading_engine.domain.enums import OrderType, ProductType, RiskReasonCode
from trading_engine.domain.identifiers import generate_risk_decision_id
from trading_engine.domain.models import PortfolioSnapshot, RiskDecision
from trading_engine.risk.kill_switch import KillSwitch
from trading_engine.risk.limits import RiskLimits
from trading_engine.strategy.signals import OrderIntent

_ZERO = Decimal("0")


class RiskEngine:
    """Evaluates OrderIntents against configured limits.

    Args:
        limits:       RiskLimits instance with all thresholds.
        kill_switch:  Optional KillSwitch; if None, one is created (starts inactive).
        logger:       Optional logger.
    """

    def __init__(
        self,
        limits: RiskLimits,
        kill_switch: KillSwitch | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._limits = limits
        self._kill_switch = kill_switch or KillSwitch()
        self._logger = logger or logging.getLogger(__name__)
        # Intraday state — reset via reset_daily_state() at start of each day.
        self._trades_today: int = 0
        self._order_timestamps: deque[datetime] = deque()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_order_intent(
        self,
        intent: OrderIntent,
        portfolio_snapshot: PortfolioSnapshot,
        current_timestamp: datetime | None = None,
    ) -> RiskDecision:
        """Run all pre-trade checks and return a RiskDecision.

        Args:
            intent:              The OrderIntent to evaluate.
            portfolio_snapshot:  Current portfolio state (read-only).
            current_timestamp:   Timestamp of the current bar/event.  Used for
                                 rate-limit checks.  Defaults to utcnow().

        Returns:
            RiskDecision with approved=True on pass, approved=False otherwise.
        """
        ts = current_timestamp or datetime.utcnow()

        decision = (
            self._check_kill_switch(ts)
            or self._check_symbol(intent, ts)
            or self._check_product(intent, ts)
            or self._check_order_type(intent, ts)
            or self._check_order_value(intent, portfolio_snapshot, ts)
            or self._check_position_count(intent, portfolio_snapshot, ts)
            or self._check_daily_loss(portfolio_snapshot, ts)
            or self._check_trades_per_day(ts)
            or self._check_orders_per_second(ts)
        )

        if decision is not None:
            self._logger.warning(
                "Risk rejected %s %s %s: %s",
                intent.side,
                intent.symbol,
                intent.order_type,
                decision.reason_code,
            )
            return decision

        # Approved — record the order for rate tracking.
        self._order_timestamps.append(ts)
        self._trades_today += 1
        return self._approve(ts)

    def on_fill(self) -> None:
        """Notify the risk engine that a fill occurred.

        Call this after each successful execution so trade counts stay accurate.
        In backtest v1 the engine counts intents that passed risk, not fills.
        This method is provided as a seam for live/paper integration.
        """

    def reset_daily_state(self) -> None:
        """Reset intraday counters.  Call at the start of each new trading day."""
        self._trades_today = 0
        self._order_timestamps.clear()

    # ------------------------------------------------------------------
    # Kill switch pass-through
    # ------------------------------------------------------------------

    @property
    def kill_switch(self) -> KillSwitch:
        return self._kill_switch

    # ------------------------------------------------------------------
    # Individual checks (return None = passed, RiskDecision = rejected)
    # ------------------------------------------------------------------

    def _check_kill_switch(self, ts: datetime) -> RiskDecision | None:
        if self._kill_switch.is_active():
            return self._reject(
                RiskReasonCode.KILL_SWITCH_ACTIVE,
                f"Kill switch active: {self._kill_switch.reason}",
                ts,
            )
        return None

    def _check_symbol(self, intent: OrderIntent, ts: datetime) -> RiskDecision | None:
        if self._limits.allowed_symbols is not None:
            if intent.symbol not in self._limits.allowed_symbols:
                return self._reject(
                    RiskReasonCode.SYMBOL_NOT_ALLOWED,
                    f"Symbol {intent.symbol!r} is not in the allowed list.",
                    ts,
                )
        return None

    def _check_product(self, intent: OrderIntent, ts: datetime) -> RiskDecision | None:
        if self._limits.allowed_product_types is not None:
            product = ProductType(intent.product)
            if product not in self._limits.allowed_product_types:
                return self._reject(
                    RiskReasonCode.PRODUCT_NOT_ALLOWED,
                    f"Product type {intent.product!r} is not allowed.",
                    ts,
                )
        return None

    def _check_order_type(self, intent: OrderIntent, ts: datetime) -> RiskDecision | None:
        if self._limits.allowed_order_types is not None:
            # Map string to OrderType enum (handles "SL-M" → SL_M).
            try:
                ot = OrderType(intent.order_type)
            except ValueError:
                return self._reject(
                    RiskReasonCode.ORDER_TYPE_NOT_ALLOWED,
                    f"Unrecognised order type {intent.order_type!r}.",
                    ts,
                )
            if ot not in self._limits.allowed_order_types:
                return self._reject(
                    RiskReasonCode.ORDER_TYPE_NOT_ALLOWED,
                    f"Order type {intent.order_type!r} is not allowed.",
                    ts,
                )
        return None

    def _check_order_value(
        self,
        intent: OrderIntent,
        snapshot: PortfolioSnapshot,
        ts: datetime,
    ) -> RiskDecision | None:
        price = self._estimate_price(intent, snapshot)
        if price is None:
            return self._reject(
                RiskReasonCode.INVALID_ORDER,
                f"Cannot determine order value for {intent.symbol}: no price available.",
                ts,
            )
        order_value = Decimal(str(intent.quantity)) * price
        if order_value > self._limits.max_order_value:
            return self._reject(
                RiskReasonCode.ORDER_VALUE_LIMIT_BREACHED,
                f"Order value {order_value} exceeds max {self._limits.max_order_value}.",
                ts,
                checked={
                    "order_value": str(order_value),
                    "limit": str(self._limits.max_order_value),
                },
            )
        return None

    def _check_position_count(
        self,
        intent: OrderIntent,
        snapshot: PortfolioSnapshot,
        ts: datetime,
    ) -> RiskDecision | None:
        if intent.side != "BUY":
            return None
        open_positions = sum(1 for p in snapshot.positions if p.quantity > 0)
        # Allow the order if we already have a position in this symbol (adding to it).
        already_held = any(p.symbol == intent.symbol and p.quantity > 0 for p in snapshot.positions)
        if not already_held and open_positions >= self._limits.max_open_positions:
            return self._reject(
                RiskReasonCode.POSITION_LIMIT_BREACHED,
                f"Open positions ({open_positions}) at or above limit "
                f"({self._limits.max_open_positions}).",
                ts,
                checked={
                    "open_positions": open_positions,
                    "limit": self._limits.max_open_positions,
                },
            )
        return None

    def _check_daily_loss(
        self,
        snapshot: PortfolioSnapshot,
        ts: datetime,
    ) -> RiskDecision | None:
        total_pnl = snapshot.realized_pnl + snapshot.unrealized_pnl
        if total_pnl < _ZERO and abs(total_pnl) > self._limits.max_daily_loss:
            return self._reject(
                RiskReasonCode.DAILY_LOSS_LIMIT_BREACHED,
                f"Daily loss {total_pnl} exceeds limit -{self._limits.max_daily_loss}.",
                ts,
                checked={
                    "daily_pnl": str(total_pnl),
                    "limit": str(-self._limits.max_daily_loss),
                },
            )
        return None

    def _check_trades_per_day(self, ts: datetime) -> RiskDecision | None:
        if self._trades_today >= self._limits.max_trades_per_day:
            return self._reject(
                RiskReasonCode.RATE_LIMIT_BREACHED,
                f"Trades today ({self._trades_today}) at or above daily limit "
                f"({self._limits.max_trades_per_day}).",
                ts,
                checked={
                    "trades_today": self._trades_today,
                    "limit": self._limits.max_trades_per_day,
                },
            )
        return None

    def _check_orders_per_second(self, ts: datetime) -> RiskDecision | None:
        # Prune timestamps older than 1 second.
        while self._order_timestamps and (ts - self._order_timestamps[0]).total_seconds() >= 1:
            self._order_timestamps.popleft()
        if len(self._order_timestamps) >= self._limits.max_orders_per_second:
            return self._reject(
                RiskReasonCode.RATE_LIMIT_BREACHED,
                f"Orders per second ({len(self._order_timestamps)}) at or above limit "
                f"({self._limits.max_orders_per_second}).",
                ts,
                checked={
                    "orders_this_second": len(self._order_timestamps),
                    "limit": self._limits.max_orders_per_second,
                },
            )
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _estimate_price(self, intent: OrderIntent, snapshot: PortfolioSnapshot) -> Decimal | None:
        """Return best available price estimate for the intent."""
        if intent.price is not None:
            return intent.price
        if intent.trigger_price is not None:
            return intent.trigger_price
        # Fall back to last known price from the portfolio snapshot.
        for pos in snapshot.positions:
            if pos.symbol == intent.symbol and pos.last_price is not None:
                return pos.last_price
            if pos.symbol == intent.symbol and pos.average_price > _ZERO:
                return pos.average_price
        return None

    def _approve(self, ts: datetime) -> RiskDecision:
        return RiskDecision(
            risk_decision_id=generate_risk_decision_id(),
            approved=True,
            reason_code=RiskReasonCode.APPROVED,
            reason_message="All risk checks passed.",
            timestamp=ts,
        )

    def _reject(
        self,
        reason_code: RiskReasonCode,
        reason_message: str,
        ts: datetime,
        checked: dict | None = None,
    ) -> RiskDecision:
        return RiskDecision(
            risk_decision_id=generate_risk_decision_id(),
            approved=False,
            reason_code=reason_code,
            reason_message=reason_message,
            checked_limits=checked or {},
            timestamp=ts,
        )
