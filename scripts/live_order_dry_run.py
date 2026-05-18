"""Live order dry-run preview tool.

Demonstrates what a live order would look like — risk check, approval status,
estimated value — without placing any order or calling Zerodha.

Usage:
  python3 scripts/live_order_dry_run.py \\
    --symbol RELIANCE \\
    --side BUY \\
    --quantity 1 \\
    --order-type MARKET \\
    --strategy-id manual_dry_run

Output: JSON preview printed to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trading_engine.live_execution.approvals import LiveOrderApprovalGate  # noqa: E402
from trading_engine.live_execution.dry_run import DryRunExecutor  # noqa: E402
from trading_engine.live_execution.models import ApprovalMode  # noqa: E402
from trading_engine.strategy.signals import OrderIntent  # noqa: E402

_VALID_SIDES = {"BUY", "SELL"}
_VALID_ORDER_TYPES = {"MARKET", "LIMIT", "SL", "SL-M"}
_VALID_PRODUCTS = {"MIS", "CNC", "NRML"}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preview what a live order would look like without placing it.\n"
            "No Zerodha API calls are made. No orders are placed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--symbol", required=True, help="Trading symbol, e.g. RELIANCE")
    parser.add_argument(
        "--side",
        required=True,
        choices=list(_VALID_SIDES),
        help="Order side: BUY or SELL",
    )
    parser.add_argument("--quantity", required=True, type=int, help="Number of shares")
    parser.add_argument(
        "--order-type",
        required=True,
        choices=list(_VALID_ORDER_TYPES),
        dest="order_type",
        help="Order type: MARKET, LIMIT, SL, or SL-M",
    )
    parser.add_argument(
        "--price",
        default=None,
        help="Limit/trigger price (required for LIMIT, optional for MARKET as estimated price)",
    )
    parser.add_argument(
        "--product",
        default="MIS",
        choices=list(_VALID_PRODUCTS),
        help="Product type: MIS (default), CNC, or NRML",
    )
    parser.add_argument(
        "--strategy-id",
        default="manual_dry_run",
        dest="strategy_id",
        help="Strategy identifier (default: manual_dry_run)",
    )
    parser.add_argument(
        "--exchange",
        default="NSE",
        help="Exchange (default: NSE)",
    )
    return parser.parse_args(argv)


def _build_intent(args: argparse.Namespace) -> OrderIntent:
    """Build an OrderIntent from parsed CLI args, with validation."""
    if args.quantity <= 0:
        print(f"[ERROR] --quantity must be positive, got {args.quantity}")
        sys.exit(1)

    price: Decimal | None = None
    if args.price is not None:
        try:
            price = Decimal(args.price)
            if price <= 0:
                print(f"[ERROR] --price must be positive, got {price}")
                sys.exit(1)
        except InvalidOperation:
            print(f"[ERROR] --price is not a valid number: {args.price!r}")
            sys.exit(1)

    if args.order_type == "LIMIT" and price is None:
        print("[ERROR] LIMIT orders require --price.")
        sys.exit(1)

    if args.order_type in ("SL", "SL-M") and price is None:
        print(f"[ERROR] {args.order_type} orders require --price as trigger price.")
        sys.exit(1)

    try:
        return OrderIntent(
            strategy_id=args.strategy_id,
            symbol=args.symbol.upper(),
            exchange=args.exchange.upper(),
            side=args.side,
            quantity=args.quantity,
            order_type=args.order_type,
            product=args.product,
            price=price if args.order_type == "LIMIT" else None,
            trigger_price=price if args.order_type in ("SL", "SL-M") else None,
        )
    except Exception as exc:
        print(f"[ERROR] Invalid order: {exc}")
        sys.exit(1)


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns exit code."""
    args = _parse_args(argv)
    intent = _build_intent(args)

    # Estimated price for value calculation (use --price for LIMIT/SL, else None)
    estimated_price: Decimal | None = None
    if args.price is not None:
        try:
            estimated_price = Decimal(args.price)
        except InvalidOperation:
            pass

    # Build dry-run executor with AUTO_PAPER approval gate (no real orders).
    gate = LiveOrderApprovalGate(mode=ApprovalMode.AUTO_PAPER)
    executor = DryRunExecutor(approval_gate=gate)

    preview = executor.preview(intent, estimated_price=estimated_price)
    print(json.dumps(preview.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
