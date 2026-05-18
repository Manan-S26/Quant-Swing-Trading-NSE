"""Write a demo dashboard session JSON without Zerodha, credentials, or live data.

Generates a realistic StatusPage-compatible dict and writes it to the default
dashboard session file so the Streamlit dashboard can be explored immediately.

Usage:
    python3 scripts/write_demo_dashboard_status.py
    python3 scripts/write_demo_dashboard_status.py --output data/dashboard/session_status.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))

from trading_engine.dashboard.session_writer import DashboardSessionWriter  # noqa: E402

_DEFAULT_OUTPUT = "data/dashboard/session_status.json"

_DEMO_STATUS = {
    "orders_by_status": {
        "RISK_APPROVED": 3,
        "SUBMITTED": 1,
        "OPEN": 2,
        "FILLED": 5,
        "RISK_REJECTED": 1,
    },
    "total_orders": 12,
    "total_fills": 5,
    "total_risk_decisions": 12,
    "open_positions_count": 2,
    "last_reconciliation_timestamp": "2024-01-15T09:45:00",
    "last_reconciliation_success": True,
    "discrepancy_count": 0,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write demo dashboard status JSON.")
    parser.add_argument(
        "--output",
        default=_DEFAULT_OUTPUT,
        help=f"Output path (default: {_DEFAULT_OUTPUT})",
    )
    args = parser.parse_args(argv)

    writer = DashboardSessionWriter(args.output)
    path = writer.write_status(_DEMO_STATUS, source="demo")
    print(f"Demo dashboard status written to: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
