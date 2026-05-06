"""Indian equity intraday cost model (simplified).

Approximates real brokerage + statutory charges for NSE MIS (intraday) trades.
Rates are defaults only — override via constructor for accuracy.

Charge breakdown (approximate, as of 2024):
  - Brokerage:         flat Rs.20 per executed order (Zerodha), capped
  - STT:               0.025% on sell-side turnover (intraday)
  - Exchange txn fee:  0.00325% of turnover (NSE)
  - SEBI charges:      0.0001% of turnover
  - Stamp duty:        0.003% on buy-side (varies by state; using Maharashtra)
  - GST:               18% on (brokerage + exchange txn fee + SEBI charges)

All rates are configurable. Exact rates should be maintained from
the application config in later milestones.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


class CostModel:
    """Calculates total transaction costs for a single fill.

    Args:
        brokerage_per_order:   Flat brokerage per executed order (INR).
        brokerage_cap:         Maximum brokerage per order (INR). Set equal to
                               brokerage_per_order for a fixed-fee broker.
        stt_rate:              STT as a fraction of sell-side turnover.
        exchange_txn_rate:     Exchange transaction charge as a fraction of turnover.
        sebi_rate:             SEBI turnover charge as a fraction of turnover.
        stamp_duty_rate:       Stamp duty as a fraction of buy-side turnover.
        gst_rate:              GST as a fraction of (brokerage + exchange + sebi).
    """

    def __init__(
        self,
        brokerage_per_order: Decimal = Decimal("20"),
        brokerage_cap: Decimal = Decimal("20"),
        stt_rate: Decimal = Decimal("0.00025"),
        exchange_txn_rate: Decimal = Decimal("0.0000325"),
        sebi_rate: Decimal = Decimal("0.000001"),
        stamp_duty_rate: Decimal = Decimal("0.00003"),
        gst_rate: Decimal = Decimal("0.18"),
    ) -> None:
        if brokerage_per_order < 0:
            raise ValueError("brokerage_per_order cannot be negative")
        if brokerage_cap < 0:
            raise ValueError("brokerage_cap cannot be negative")
        if any(r < 0 for r in (stt_rate, exchange_txn_rate, sebi_rate, stamp_duty_rate, gst_rate)):
            raise ValueError("Rate parameters cannot be negative")

        self.brokerage_per_order = brokerage_per_order
        self.brokerage_cap = brokerage_cap
        self.stt_rate = stt_rate
        self.exchange_txn_rate = exchange_txn_rate
        self.sebi_rate = sebi_rate
        self.stamp_duty_rate = stamp_duty_rate
        self.gst_rate = gst_rate

    def calculate_fees(self, side: str, quantity: int, price: Decimal) -> Decimal:
        """Return total transaction fees for a single executed order.

        Args:
            side:     "BUY" or "SELL".
            quantity: Number of shares.
            price:    Fill price per share.

        Returns:
            Total fees in INR (non-negative Decimal).
        """
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")
        if price <= 0:
            raise ValueError(f"price must be positive, got {price}")
        if side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {side!r}")

        turnover = Decimal(str(quantity)) * price

        # Brokerage: flat per order, capped.
        brokerage = min(self.brokerage_per_order, self.brokerage_cap)

        # STT: charged on sell-side turnover for intraday equity.
        stt = self.stt_rate * turnover if side == "SELL" else Decimal("0")

        # Exchange transaction charge: both sides.
        exchange_txn = self.exchange_txn_rate * turnover

        # SEBI charge: both sides.
        sebi = self.sebi_rate * turnover

        # Stamp duty: charged on buy-side only.
        stamp = self.stamp_duty_rate * turnover if side == "BUY" else Decimal("0")

        # GST: on brokerage + exchange txn + SEBI (not on STT or stamp).
        gst = self.gst_rate * (brokerage + exchange_txn + sebi)

        total = brokerage + stt + exchange_txn + sebi + stamp + gst
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
