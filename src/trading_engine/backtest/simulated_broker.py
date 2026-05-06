"""Simulated broker for the backtesting engine.

Executes OrderIntents against historical bars without any real broker calls.
Supports MARKET and LIMIT orders. SL/SL-M are not supported in v1.
"""

from __future__ import annotations

from decimal import Decimal

from trading_engine.backtest.cost_model import CostModel
from trading_engine.backtest.portfolio import BacktestPortfolio
from trading_engine.backtest.slippage_model import SlippageModel
from trading_engine.domain.enums import Exchange, Side
from trading_engine.domain.identifiers import generate_fill_id, generate_internal_order_id
from trading_engine.domain.models import TradeFill
from trading_engine.strategy.signals import Bar, OrderIntent


class UnsupportedOrderTypeError(Exception):
    """Raised when an order type is not supported by the simulated broker."""


class SimulatedBroker:
    """Executes OrderIntents against the current bar.

    Args:
        portfolio:      BacktestPortfolio to update on fills.
        cost_model:     CostModel for fee calculation.
        slippage_model: SlippageModel for fill price adjustment.
    """

    def __init__(
        self,
        portfolio: BacktestPortfolio,
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
                f"Order type {order_type!r} is not supported in backtest v1. "
                "Use MARKET or LIMIT orders."
            )

        side = order_intent.side
        fill_price: Decimal | None = None

        if order_type == "MARKET":
            fill_price = self._slippage_model.apply(side, current_bar.close)

        elif order_type == "LIMIT":
            limit_price = order_intent.price
            if limit_price is None:
                raise ValueError("LIMIT order has no price set on OrderIntent")

            if side == "BUY":
                # Fill if bar touched or went below the limit.
                if current_bar.low <= limit_price:
                    fill_price = self._slippage_model.apply(side, limit_price)
            else:  # SELL
                # Fill if bar touched or went above the limit.
                if current_bar.high >= limit_price:
                    fill_price = self._slippage_model.apply(side, limit_price)

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
