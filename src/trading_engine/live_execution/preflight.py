"""Live pilot preflight checker.

LivePilotPreflightChecker runs a suite of configuration and environment checks
before any live order session.  It does not place orders, does not call Zerodha
APIs, and does not print secrets.

Usage::

    from trading_engine.live_execution.preflight import LivePilotPreflightChecker
    from trading_engine.common.config import load_settings

    settings = load_settings()
    checker = LivePilotPreflightChecker(settings)
    report = checker.run()
    print(report.summary())

Checks are labelled REQUIRED or ADVISORY.  REQUIRED checks that FAIL cause
exit code 1 in the CLI.  ADVISORY checks produce WARN status and do not fail.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class CheckStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class CheckLevel(StrEnum):
    REQUIRED = "REQUIRED"
    ADVISORY = "ADVISORY"


@dataclass
class PreflightCheck:
    """Result of a single preflight check.

    Attributes:
        name:        Short identifier for the check.
        status:      PASS, WARN, or FAIL.
        level:       REQUIRED or ADVISORY.
        message:     Human-readable explanation of the result.
        detail:      Optional extra detail (does not contain secrets).
    """

    name: str
    status: CheckStatus
    level: CheckLevel
    message: str
    detail: str | None = None

    def passed(self) -> bool:
        return self.status == CheckStatus.PASS

    def failed(self) -> bool:
        return self.status == CheckStatus.FAIL

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": str(self.status),
            "level": str(self.level),
            "message": self.message,
            "detail": self.detail,
        }


@dataclass
class PreflightReport:
    """Aggregated result of all preflight checks.

    Attributes:
        checks:  All individual check results.
        passed:  True if all REQUIRED checks have status PASS.
    """

    checks: list[PreflightCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True if every REQUIRED check is PASS (WARNs and ADVISORY FAILs do not count)."""
        return all(
            c.status == CheckStatus.PASS for c in self.checks if c.level == CheckLevel.REQUIRED
        )

    @property
    def required_failures(self) -> list[PreflightCheck]:
        return [
            c
            for c in self.checks
            if c.level == CheckLevel.REQUIRED and c.status == CheckStatus.FAIL
        ]

    @property
    def warnings(self) -> list[PreflightCheck]:
        return [c for c in self.checks if c.status == CheckStatus.WARN]

    def summary(self) -> str:
        """Return a human-readable multi-line summary table."""
        lines = ["Preflight Check Results", "=" * 60]
        for c in self.checks:
            icon = {"PASS": "✓", "WARN": "!", "FAIL": "✗"}.get(str(c.status), "?")
            lines.append(f"  [{icon}] {c.status:<4}  {c.level:<8}  {c.name}")
            lines.append(f"           {c.message}")
            if c.detail:
                lines.append(f"           Detail: {c.detail}")
        lines.append("=" * 60)
        status_str = "ALL REQUIRED CHECKS PASSED" if self.passed else "REQUIRED CHECKS FAILED"
        lines.append(f"  Result: {status_str}")
        lines.append(
            f"  {sum(1 for c in self.checks if c.passed())} passed, "
            f"{len(self.warnings)} warnings, "
            f"{len(self.required_failures)} required failures"
        )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [c.to_dict() for c in self.checks],
            "summary": {
                "total": len(self.checks),
                "pass": sum(1 for c in self.checks if c.passed()),
                "warn": len(self.warnings),
                "required_failures": len(self.required_failures),
            },
        }


class LivePilotPreflightChecker:
    """Runs all preflight checks for a live order pilot session.

    Args:
        settings:                  Settings instance (pydantic-settings or any object
                                   with the expected attributes).
        audit_log_path:            Override path for audit log writability check.
        dashboard_path:            Override path for dashboard writability check.
        require_static_ip:         If True, adds a REQUIRED check for static IP confirmation.
                                   Defaults to False (ADVISORY warning only).
        kill_switch:               Optional KillSwitch instance.  If None, kill switch
                                   check is skipped.
    """

    # Maximum allowed pilot quantity before a warning is issued.
    _WARN_QUANTITY_THRESHOLD = 5

    def __init__(
        self,
        settings: Any,
        audit_log_path: str | Path | None = None,
        dashboard_path: str | Path | None = None,
        require_static_ip: bool = False,
        kill_switch: Any | None = None,
    ) -> None:
        self._settings = settings
        self._audit_log_path = Path(audit_log_path) if audit_log_path else Path("data/audit")
        self._dashboard_path = Path(dashboard_path) if dashboard_path else None
        self._require_static_ip = require_static_ip
        self._kill_switch = kill_switch

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> PreflightReport:
        """Execute all preflight checks and return a PreflightReport."""
        report = PreflightReport()
        report.checks.extend(self._check_flags())
        report.checks.extend(self._check_pilot_constraints())
        report.checks.extend(self._check_credentials())
        report.checks.extend(self._check_filesystem())
        report.checks.extend(self._check_kill_switch())
        report.checks.extend(self._check_static_ip())
        return report

    # ------------------------------------------------------------------
    # Flag checks
    # ------------------------------------------------------------------

    def _check_flags(self) -> list[PreflightCheck]:
        checks = []
        s = self._settings

        live_enabled = getattr(s, "live_trading_enabled", False)
        checks.append(
            PreflightCheck(
                name="LIVE_TRADING_ENABLED",
                status=CheckStatus.PASS if live_enabled else CheckStatus.FAIL,
                level=CheckLevel.REQUIRED,
                message=(
                    "LIVE_TRADING_ENABLED=true"
                    if live_enabled
                    else "LIVE_TRADING_ENABLED is false — set to true for pilot."
                ),
            )
        )

        exec_enabled = getattr(s, "live_order_execution_enabled", False)
        checks.append(
            PreflightCheck(
                name="LIVE_ORDER_EXECUTION_ENABLED",
                status=CheckStatus.PASS if exec_enabled else CheckStatus.FAIL,
                level=CheckLevel.REQUIRED,
                message=(
                    "LIVE_ORDER_EXECUTION_ENABLED=true"
                    if exec_enabled
                    else "LIVE_ORDER_EXECUTION_ENABLED is false — set to true for pilot."
                ),
            )
        )

        pilot_enabled = getattr(s, "live_order_pilot_enabled", False)
        checks.append(
            PreflightCheck(
                name="LIVE_ORDER_PILOT_ENABLED",
                status=CheckStatus.PASS if pilot_enabled else CheckStatus.FAIL,
                level=CheckLevel.REQUIRED,
                message=(
                    "LIVE_ORDER_PILOT_ENABLED=true"
                    if pilot_enabled
                    else "LIVE_ORDER_PILOT_ENABLED is false — set to true for pilot."
                ),
            )
        )

        return checks

    # ------------------------------------------------------------------
    # Pilot constraint checks
    # ------------------------------------------------------------------

    def _check_pilot_constraints(self) -> list[PreflightCheck]:
        checks = []
        s = self._settings

        # Max order quantity
        max_qty = getattr(s, "live_max_order_quantity", 1)
        if max_qty <= 0:
            status = CheckStatus.FAIL
            msg = f"LIVE_MAX_ORDER_QUANTITY={max_qty} — must be positive."
        elif max_qty > self._WARN_QUANTITY_THRESHOLD:
            status = CheckStatus.WARN
            msg = f"LIVE_MAX_ORDER_QUANTITY={max_qty} — consider lowering to 1 for first pilot."
        else:
            status = CheckStatus.PASS
            msg = f"LIVE_MAX_ORDER_QUANTITY={max_qty}"
        checks.append(
            PreflightCheck(
                name="LIVE_MAX_ORDER_QUANTITY",
                status=status,
                level=CheckLevel.REQUIRED,
                message=msg,
            )
        )

        # Allowed symbols
        symbols = getattr(s, "live_allowed_symbols", [])
        if not symbols:
            st = CheckStatus.FAIL
            msg = "LIVE_ALLOWED_SYMBOLS is empty — no orders can be placed."
        else:
            st = CheckStatus.PASS
            msg = f"LIVE_ALLOWED_SYMBOLS has {len(symbols)} symbol(s): {symbols}"
        checks.append(
            PreflightCheck(
                name="LIVE_ALLOWED_SYMBOLS",
                status=st,
                level=CheckLevel.REQUIRED,
                message=msg,
            )
        )

        # Product
        product = getattr(s, "live_allowed_product", "").upper()
        if product != "MIS":
            st = CheckStatus.WARN
            msg = f"LIVE_ALLOWED_PRODUCT={product!r} — expected MIS for intraday NSE trading."
        else:
            st = CheckStatus.PASS
            msg = "LIVE_ALLOWED_PRODUCT=MIS (intraday, auto-squared at end of day)"
        checks.append(
            PreflightCheck(
                name="LIVE_ALLOWED_PRODUCT",
                status=st,
                level=CheckLevel.ADVISORY,
                message=msg,
            )
        )

        # Exchange
        exchange = getattr(s, "live_allowed_exchange", "").upper()
        if exchange != "NSE":
            st = CheckStatus.WARN
            msg = f"LIVE_ALLOWED_EXCHANGE={exchange!r} — expected NSE for this engine."
        else:
            st = CheckStatus.PASS
            msg = "LIVE_ALLOWED_EXCHANGE=NSE"
        checks.append(
            PreflightCheck(
                name="LIVE_ALLOWED_EXCHANGE",
                status=st,
                level=CheckLevel.ADVISORY,
                message=msg,
            )
        )

        # Order types
        _allowed = {"MARKET", "LIMIT"}
        order_types = [ot.upper() for ot in getattr(s, "live_allowed_order_types", [])]
        extra = set(order_types) - _allowed
        if not order_types:
            st = CheckStatus.FAIL
            msg = "LIVE_ALLOWED_ORDER_TYPES is empty — no orders can be placed."
            level = CheckLevel.REQUIRED
        elif extra:
            st = CheckStatus.WARN
            msg = (
                f"LIVE_ALLOWED_ORDER_TYPES contains non-standard types: {sorted(extra)}. "
                "Only MARKET and LIMIT are recommended for pilot."
            )
            level = CheckLevel.ADVISORY
        else:
            st = CheckStatus.PASS
            msg = f"LIVE_ALLOWED_ORDER_TYPES={order_types}"
            level = CheckLevel.ADVISORY
        checks.append(
            PreflightCheck(
                name="LIVE_ALLOWED_ORDER_TYPES",
                status=st,
                level=level,
                message=msg,
            )
        )

        return checks

    # ------------------------------------------------------------------
    # Credential presence checks (never reveal values)
    # ------------------------------------------------------------------

    def _check_credentials(self) -> list[PreflightCheck]:
        checks = []
        s = self._settings

        def _is_set(attr: str) -> bool:
            val = getattr(s, attr, None)
            if val is None:
                return False
            # Handle pydantic SecretStr
            raw = val.get_secret_value() if hasattr(val, "get_secret_value") else str(val)
            return bool(raw.strip())

        for attr, label in (
            ("zerodha_api_key", "ZERODHA_API_KEY"),
            ("zerodha_api_secret", "ZERODHA_API_SECRET"),
            ("zerodha_access_token", "ZERODHA_ACCESS_TOKEN"),
        ):
            present = _is_set(attr)
            checks.append(
                PreflightCheck(
                    name=label,
                    status=CheckStatus.PASS if present else CheckStatus.FAIL,
                    level=CheckLevel.REQUIRED,
                    message=(
                        f"{label} is set (value hidden)"
                        if present
                        else f"{label} is not set — required for live API calls."
                    ),
                )
            )

        return checks

    # ------------------------------------------------------------------
    # Filesystem writability checks
    # ------------------------------------------------------------------

    def _check_filesystem(self) -> list[PreflightCheck]:
        checks = []

        # Audit log directory
        audit_dir = (
            self._audit_log_path if self._audit_log_path.is_dir() else self._audit_log_path.parent
        )
        writable = _is_writable_or_creatable(audit_dir)
        checks.append(
            PreflightCheck(
                name="AUDIT_LOG_WRITABLE",
                status=CheckStatus.PASS if writable else CheckStatus.WARN,
                level=CheckLevel.ADVISORY,
                message=(
                    f"Audit log directory is writable: {audit_dir}"
                    if writable
                    else f"Audit log directory may not be writable: {audit_dir}"
                ),
            )
        )

        # Dashboard path (if configured)
        if self._dashboard_path is not None:
            dash_dir = (
                self._dashboard_path
                if self._dashboard_path.is_dir()
                else self._dashboard_path.parent
            )
            dash_writable = _is_writable_or_creatable(dash_dir)
            checks.append(
                PreflightCheck(
                    name="DASHBOARD_PATH_WRITABLE",
                    status=CheckStatus.PASS if dash_writable else CheckStatus.WARN,
                    level=CheckLevel.ADVISORY,
                    message=(
                        f"Dashboard parent directory is writable: {dash_dir}"
                        if dash_writable
                        else f"Dashboard directory may not be writable: {dash_dir}"
                    ),
                )
            )

        return checks

    # ------------------------------------------------------------------
    # Kill switch check
    # ------------------------------------------------------------------

    def _check_kill_switch(self) -> list[PreflightCheck]:
        if self._kill_switch is None:
            return [
                PreflightCheck(
                    name="KILL_SWITCH",
                    status=CheckStatus.WARN,
                    level=CheckLevel.ADVISORY,
                    message="Kill switch not provided — cannot verify state. Pass kill_switch= to checker.",
                )
            ]

        active = self._kill_switch.is_active()
        return [
            PreflightCheck(
                name="KILL_SWITCH",
                status=CheckStatus.FAIL if active else CheckStatus.PASS,
                level=CheckLevel.REQUIRED,
                message=(
                    f"Kill switch is ACTIVE — reason: {self._kill_switch.reason!r}. Deactivate before trading."
                    if active
                    else "Kill switch is inactive."
                ),
            )
        ]

    # ------------------------------------------------------------------
    # Static IP advisory
    # ------------------------------------------------------------------

    def _check_static_ip(self) -> list[PreflightCheck]:
        level = CheckLevel.REQUIRED if self._require_static_ip else CheckLevel.ADVISORY
        return [
            PreflightCheck(
                name="STATIC_IP_CONFIRMED",
                status=CheckStatus.WARN,
                level=level,
                message=(
                    "Static IP confirmation required but cannot be verified automatically. "
                    "Confirm your public IP matches the Kite Connect whitelist before proceeding."
                    if self._require_static_ip
                    else "Static IP cannot be verified automatically. "
                    "Confirm your public IP matches your Kite Connect whitelist."
                ),
                detail="Use: curl -s https://api.ipify.org to check your public IP.",
            )
        ]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _is_writable_or_creatable(path: Path) -> bool:
    """Return True if path is a writable directory, or its parents can be created."""
    try:
        if path.exists():
            return os.access(path, os.W_OK)
        # Walk up until we find an existing parent
        parent = path
        for _ in range(10):
            parent = parent.parent
            if parent.exists():
                return os.access(parent, os.W_OK)
        return False
    except Exception:
        return False
