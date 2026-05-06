"""Paper trading execution broker.

PaperExecutionBroker simulates order execution against synthetic bars.
It is NOT the same as broker/paper.py (which is the Broker-interface stub).

  broker/paper.py   — Broker-interface stub: connection lifecycle only.
  paper/broker.py   — Execution simulator: fills orders against synthetic bars.

No Zerodha imports. No real orders. No credentials.
"""

from __future__ import annotations

from decimal import Decimal

from trading_engine.backtest.cost_model import CostModel
from trading_engine.backtest.slippage_model import SlippageModel
from trading_engine.domain.enums import Exchange, Side
from trading_engine.domain.identifiers import generate_fill_id, generate_internal_order_id
from trading_engine.domain.models import TradeFill
from trading_engine.paper.portfolio import PaperPortfolio
from trading_engine.strategy.signals import Bar, OrderIntent


class UnsupportedOrderTypeError(Exception):
    """Raised when an order type is not supported by the paper execution broker."""


class PaperExecutionBroker:
    """Simulates order execution for paper trading.

    Behaviour mirrors SimulatedBroker:
    - MARKET orders fill at bar.close ± slippage.
    - LIMIT BUY fills if bar.low <= limit price.
    - LIMIT SELL fills if bar.high >= limit price.
    - SL / SL-M raise UnsupportedOrderTypeError.

    Args:
        portfolio:      PaperPortfolio to update on fills.
        cost_model:     CostModel for fee calculation.
        slippage_model: SlippageModel for fill price adjustment.
    """

    def __init__(
        self,
        portfolio: PaperPortfolio,
        cost_model: CostModel,
        slippage_model: SlippageModel,
    ) -> None:
        self._portfolio = portfolio
        self._cost_model = cost_model
        self._slippage_model = slippage_model

    def execute_order_intent(
        self,
        order_intent: OrderIntent,
        current_bar: Bar,
    ) -> TradeFill | None:
        """Attempt to fill an OrderIntent against the current bar.

        MARKET orders always fill at bar close + slippage.
        LIMIT BUY fills if bar.low <= limit price.
        LIMIT SELL fills if bar.high >= limit price.
        SL and SL-M raise UnsupportedOrderTypeError.

        Returns:
            TradeFill if filled, None if limit not touched.

        Raises:
            UnsupportedOrderTypeError: For SL or SL-M order types.
        """
        order_type = order_intent.order_type

        if order_type in ("SL", "SL-M"):
            raise UnsupportedOrderTypeError(
                f"Order type {order_type!r} is not supported in paper trading v1. "
                "Use MARKET or LIMIT orders."
            )

        side = order_intent.side
        fill_price = self._compute_fill_price(order_intent, current_bar, side)

        if fill_price is None:
            return None

        fees = self._cost_model.calculate_fees(side, order_intent.quantity, fill_price)

        fill = TradeFill(
            fill_id=generate_fill_id(),
            internal_order_id=generate_internal_order_id(),
            symbol=order_intent.symbol,
            exchange=Exchange(order_intent.exchange),
            side=Side(side),
            quantity=order_intent.quantity,
            price=fill_price,
            fees=fees,
            timestamp=current_bar.timestamp,
        )

        self._portfolio.apply_fill(fill)
        return fill

    def _compute_fill_price(
        self,
        order_intent: OrderIntent,
        current_bar: Bar,
        side: str,
    ) -> Decimal | None:
        order_type = order_intent.order_type

        if order_type == "MARKET":
            return self._slippage_model.apply(side, current_bar.close)

        if order_type == "LIMIT":
            limit_price = order_intent.price
            if limit_price is None:
                raise ValueError("LIMIT order has no price set on OrderIntent")
            if side == "BUY":
                if current_bar.low <= limit_price:
                    return self._slippage_model.apply(side, limit_price)
            else:  # SELL
                if current_bar.high >= limit_price:
                    return self._slippage_model.apply(side, limit_price)
            return None

        return None  # unreachable after SL/SL-M guard, but explicit is safer
