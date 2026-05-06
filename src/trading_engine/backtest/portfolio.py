"""Backtest portfolio tracker.

Tracks cash, positions, realized/unrealized P&L, and equity over time.
Long-only in v1: a SELL that would take a position negative is rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from trading_engine.domain.enums import Exchange, ProductType, Side
from trading_engine.domain.models import PortfolioSnapshot, Position, TradeFill


class InsufficientPositionError(Exception):
    """Raised when a SELL would exceed the current long position."""


@dataclass
class _PositionState:
    """Mutable internal position state."""

    symbol: str
    exchange: Exchange
    product: ProductType
    quantity: int = 0
    average_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    last_price: Decimal | None = None
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_position(self) -> Position:
        return Position(
            symbol=self.symbol,
            exchange=self.exchange,
            product=self.product,
            quantity=self.quantity,
            average_price=self.average_price,
            last_price=self.last_price,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=self.unrealized_pnl,
            updated_at=self.updated_at,
        )


class BacktestPortfolio:
    """Tracks cash, positions, and P&L for a backtest run.

    Args:
        initial_cash:       Starting cash balance in INR.
        exchange:           Default exchange for position tracking.
        product:            Default product type for position tracking.
    """

    def __init__(
        self,
        initial_cash: Decimal,
        exchange: Exchange = Exchange.NSE,
        product: ProductType = ProductType.MIS,
    ) -> None:
        if initial_cash <= 0:
            raise ValueError(f"initial_cash must be positive, got {initial_cash}")
        self._cash: Decimal = initial_cash
        self._exchange = exchange
        self._product = product
        self._positions: dict[str, _PositionState] = {}
        self._fills: list[TradeFill] = []
        self._equity_curve: list[tuple[datetime, Decimal]] = []
        self._total_fees: Decimal = Decimal("0")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def cash(self) -> Decimal:
        return self._cash

    @property
    def fills(self) -> list[TradeFill]:
        return list(self._fills)

    @property
    def equity_curve(self) -> list[tuple[datetime, Decimal]]:
        return list(self._equity_curve)

    @property
    def total_fees(self) -> Decimal:
        return self._total_fees

    def total_equity(self, latest_prices: dict[str, Decimal] | None = None) -> Decimal:
        """Cash + market value of all open positions."""
        prices = latest_prices or {}
        equity = self._cash
        for sym, pos in self._positions.items():
            if pos.quantity > 0:
                price = prices.get(sym, pos.average_price)
                equity += Decimal(str(pos.quantity)) * price
        return equity

    def get_position(self, symbol: str) -> _PositionState | None:
        return self._positions.get(symbol)

    def apply_fill(self, fill: TradeFill) -> None:
        """Update cash and position state from a trade fill.

        For BUY: increases position, reduces cash (including fees).
        For SELL: reduces position, increases cash, books realized P&L.

        Raises:
            InsufficientPositionError: If SELL quantity > current long position.
        """
        symbol = fill.symbol
        qty = Decimal(str(fill.quantity))
        gross_value = qty * fill.price

        if fill.side == Side.BUY:
            self._cash -= gross_value + fill.fees
            pos = self._positions.setdefault(
                symbol,
                _PositionState(
                    symbol=symbol,
                    exchange=fill.exchange,
                    product=self._product,
                    updated_at=fill.timestamp,
                ),
            )
            # Update average price (weighted average).
            existing_value = Decimal(str(pos.quantity)) * pos.average_price
            pos.quantity += fill.quantity
            pos.average_price = (existing_value + gross_value) / Decimal(str(pos.quantity))
            pos.updated_at = fill.timestamp

        elif fill.side == Side.SELL:
            pos = self._positions.get(symbol)
            current_qty = pos.quantity if pos else 0
            if current_qty < fill.quantity:
                raise InsufficientPositionError(
                    f"Cannot sell {fill.quantity} of {symbol}: only {current_qty} held."
                )
            cost_basis = Decimal(str(fill.quantity)) * pos.average_price
            realized = gross_value - cost_basis - fill.fees
            pos.realized_pnl += realized
            pos.quantity -= fill.quantity
            pos.updated_at = fill.timestamp
            self._cash += gross_value - fill.fees

        self._total_fees += fill.fees
        self._fills.append(fill)

    def mark_to_market(self, timestamp: datetime, latest_prices: dict[str, Decimal]) -> None:
        """Update unrealized P&L and record equity curve point."""
        for sym, pos in self._positions.items():
            if pos.quantity > 0 and sym in latest_prices:
                price = latest_prices[sym]
                pos.last_price = price
                pos.unrealized_pnl = (
                    Decimal(str(pos.quantity)) * price
                    - Decimal(str(pos.quantity)) * pos.average_price
                )
        equity = self.total_equity(latest_prices)
        self._equity_curve.append((timestamp, equity))

    def get_snapshot(self, timestamp: datetime) -> PortfolioSnapshot:
        """Return a PortfolioSnapshot of the current state."""
        positions = [p.to_position() for p in self._positions.values()]
        realized = sum((p.realized_pnl for p in self._positions.values()), Decimal("0"))
        unrealized = sum((p.unrealized_pnl for p in self._positions.values()), Decimal("0"))
        gross_exposure = sum(
            (
                Decimal(str(p.quantity)) * (p.last_price or p.average_price)
                for p in self._positions.values()
                if p.quantity > 0
            ),
            Decimal("0"),
        )
        return PortfolioSnapshot(
            timestamp=timestamp,
            cash=self._cash,
            positions=positions,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            gross_exposure=gross_exposure,
            net_exposure=gross_exposure,  # Long-only: net == gross
        )
