"""Slippage model for the backtesting engine.

Models market impact as a fixed basis-point spread applied to fill prices.
BUY orders fill slightly above the quoted price; SELL orders slightly below.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_TEN_THOUSAND = Decimal("10000")
_ONE = Decimal("1")


class SlippageModel:
    """Applies a fixed basis-point slippage to fill prices.

    Args:
        bps: Slippage in basis points (1 bp = 0.01%). Must be >= 0.
             Default 2 bps is conservative for liquid NSE large-caps.
    """

    def __init__(self, bps: Decimal = Decimal("2")) -> None:
        if bps < 0:
            raise ValueError(f"bps cannot be negative, got {bps}")
        self.bps = bps

    def apply(self, side: str, price: Decimal) -> Decimal:
        """Return the slippage-adjusted fill price.

        Args:
            side:  "BUY" or "SELL".
            price: Reference price (e.g. bar close or limit price).

        Returns:
            Adjusted price (Decimal, rounded to 2 decimal places).
        """
        if price <= 0:
            raise ValueError(f"price must be positive, got {price}")
        if side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {side!r}")

        factor = self.bps / _TEN_THOUSAND  # bps → fraction
        adjustment = price * factor

        if side == "BUY":
            result = price + adjustment
        else:
            result = price - adjustment

        return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
