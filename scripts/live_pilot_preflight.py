"""Live pilot preflight check CLI.

Runs configuration and environment checks before any live order session.
Does not place orders, does not call Zerodha order APIs.

Usage::

    python3 scripts/live_pilot_preflight.py
    python3 scripts/live_pilot_preflight.py --json
    python3 scripts/live_pilot_preflight.py --require-static-ip-confirmed
    python3 scripts/live_pilot_preflight.py --audit-log-path data/audit/orders.jsonl
    python3 scripts/live_pilot_preflight.py --dashboard-path data/dashboard/status.json

Exit codes:
    0 — all REQUIRED checks passed (warnings are OK)
    1 — one or more REQUIRED checks failed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trading_engine.common.config import load_settings  # noqa: E402
from trading_engine.live_execution.preflight import LivePilotPreflightChecker  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run preflight checks for the live order pilot.\n"
            "Does not place orders. Does not call Zerodha order APIs."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output results as JSON (default: human-readable table).",
    )
    parser.add_argument(
        "--require-static-ip-confirmed",
        action="store_true",
        dest="require_static_ip",
        help=(
            "Treat the static IP check as REQUIRED rather than ADVISORY. "
            "Preflight will fail if static IP cannot be confirmed."
        ),
    )
    parser.add_argument(
        "--audit-log-path",
        default=None,
        dest="audit_log_path",
        help="Override audit log path for writability check (default: data/audit).",
    )
    parser.add_argument(
        "--dashboard-path",
        default=None,
        dest="dashboard_path",
        help="Check writability of the dashboard session file parent directory.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    settings = load_settings()

    # Optionally include kill switch check if available.
    kill_switch = None
    try:
        from trading_engine.risk.kill_switch import KillSwitch  # noqa: PLC0415

        kill_switch = KillSwitch()
    except Exception:
        pass

    checker = LivePilotPreflightChecker(
        settings=settings,
        audit_log_path=args.audit_log_path,
        dashboard_path=args.dashboard_path,
        require_static_ip=args.require_static_ip,
        kill_switch=kill_switch,
    )

    report = checker.run()

    if args.output_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.summary())

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
