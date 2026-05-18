"""Tests for live_execution.preflight — LivePilotPreflightChecker."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from trading_engine.live_execution.preflight import (
    CheckLevel,
    CheckStatus,
    LivePilotPreflightChecker,
    PreflightCheck,
    PreflightReport,
)

# ---------------------------------------------------------------------------
# Fake settings helpers
# ---------------------------------------------------------------------------


def _full_settings(**overrides: object) -> object:
    """Build a fake settings object with all live pilot flags enabled."""

    class _S:
        live_trading_enabled = True
        live_order_execution_enabled = True
        live_order_pilot_enabled = True
        live_max_order_quantity = 1
        live_allowed_symbols = ["RELIANCE"]
        live_allowed_exchange = "NSE"
        live_allowed_product = "MIS"
        live_allowed_order_types = ["MARKET", "LIMIT"]
        zerodha_api_key = _Secret("fake_key")
        zerodha_api_secret = _Secret("fake_secret")
        zerodha_access_token = _Secret("fake_token")

    s = _S()
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _disabled_settings() -> object:
    """Fake settings with all pilot flags disabled (safe defaults)."""

    class _S:
        live_trading_enabled = False
        live_order_execution_enabled = False
        live_order_pilot_enabled = False
        live_max_order_quantity = 1
        live_allowed_symbols = []
        live_allowed_exchange = "NSE"
        live_allowed_product = "MIS"
        live_allowed_order_types = ["MARKET", "LIMIT"]
        zerodha_api_key = _Secret("")
        zerodha_api_secret = _Secret("")
        zerodha_access_token = _Secret("")

    return _S()


class _Secret:
    """Minimal SecretStr-compatible fake."""

    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "**********"


class _FakeKillSwitch:
    def __init__(self, active: bool = False, reason: str | None = None) -> None:
        self._active = active
        self.reason = reason

    def is_active(self) -> bool:
        return self._active


# ---------------------------------------------------------------------------
# PreflightCheck unit tests
# ---------------------------------------------------------------------------


class TestPreflightCheck:
    def test_pass_check(self):
        c = PreflightCheck("NAME", CheckStatus.PASS, CheckLevel.REQUIRED, "ok")
        assert c.passed() is True
        assert c.failed() is False

    def test_fail_check(self):
        c = PreflightCheck("NAME", CheckStatus.FAIL, CheckLevel.REQUIRED, "bad")
        assert c.passed() is False
        assert c.failed() is True

    def test_to_dict_contains_required_keys(self):
        c = PreflightCheck("TEST", CheckStatus.WARN, CheckLevel.ADVISORY, "msg", "detail")
        d = c.to_dict()
        for key in ("name", "status", "level", "message", "detail"):
            assert key in d

    def test_to_dict_is_json_serializable(self):
        c = PreflightCheck("X", CheckStatus.PASS, CheckLevel.REQUIRED, "all good")
        json.dumps(c.to_dict())  # must not raise


# ---------------------------------------------------------------------------
# PreflightReport unit tests
# ---------------------------------------------------------------------------


class TestPreflightReport:
    def test_empty_report_passes(self):
        report = PreflightReport()
        assert report.passed is True

    def test_passes_when_all_required_pass(self):
        report = PreflightReport(
            checks=[
                PreflightCheck("A", CheckStatus.PASS, CheckLevel.REQUIRED, "ok"),
                PreflightCheck("B", CheckStatus.WARN, CheckLevel.ADVISORY, "warn"),
            ]
        )
        assert report.passed is True

    def test_fails_when_required_check_fails(self):
        report = PreflightReport(
            checks=[
                PreflightCheck("A", CheckStatus.FAIL, CheckLevel.REQUIRED, "bad"),
            ]
        )
        assert report.passed is False

    def test_advisory_fail_does_not_cause_overall_failure(self):
        report = PreflightReport(
            checks=[
                PreflightCheck("A", CheckStatus.PASS, CheckLevel.REQUIRED, "ok"),
                PreflightCheck("B", CheckStatus.FAIL, CheckLevel.ADVISORY, "advisory fail"),
            ]
        )
        assert report.passed is True

    def test_required_failures_list(self):
        report = PreflightReport(
            checks=[
                PreflightCheck("A", CheckStatus.FAIL, CheckLevel.REQUIRED, "r-fail"),
                PreflightCheck("B", CheckStatus.FAIL, CheckLevel.ADVISORY, "a-fail"),
            ]
        )
        assert len(report.required_failures) == 1
        assert report.required_failures[0].name == "A"

    def test_warnings_list(self):
        report = PreflightReport(
            checks=[
                PreflightCheck("A", CheckStatus.WARN, CheckLevel.REQUIRED, "w"),
                PreflightCheck("B", CheckStatus.PASS, CheckLevel.REQUIRED, "ok"),
            ]
        )
        assert len(report.warnings) == 1

    def test_to_dict_is_json_serializable(self):
        report = PreflightReport(
            checks=[
                PreflightCheck("X", CheckStatus.PASS, CheckLevel.REQUIRED, "ok"),
            ]
        )
        json.dumps(report.to_dict())  # must not raise

    def test_summary_contains_result_line(self):
        report = PreflightReport(
            checks=[
                PreflightCheck("A", CheckStatus.PASS, CheckLevel.REQUIRED, "ok"),
            ]
        )
        assert "PASSED" in report.summary() or "FAILED" in report.summary()


# ---------------------------------------------------------------------------
# LivePilotPreflightChecker — flag checks
# ---------------------------------------------------------------------------


class TestPreflightFlagChecks:
    def _run(self, **overrides: object) -> PreflightReport:
        return LivePilotPreflightChecker(_full_settings(**overrides)).run()

    def test_all_flags_enabled_passes(self):
        report = self._run()
        flag_checks = {c.name: c for c in report.checks if "ENABLED" in c.name}
        for c in flag_checks.values():
            assert c.status == CheckStatus.PASS

    def test_live_trading_disabled_fails(self):
        report = self._run(live_trading_enabled=False)
        c = next(c for c in report.checks if c.name == "LIVE_TRADING_ENABLED")
        assert c.status == CheckStatus.FAIL
        assert c.level == CheckLevel.REQUIRED

    def test_execution_disabled_fails(self):
        report = self._run(live_order_execution_enabled=False)
        c = next(c for c in report.checks if c.name == "LIVE_ORDER_EXECUTION_ENABLED")
        assert c.status == CheckStatus.FAIL

    def test_pilot_disabled_fails(self):
        report = self._run(live_order_pilot_enabled=False)
        c = next(c for c in report.checks if c.name == "LIVE_ORDER_PILOT_ENABLED")
        assert c.status == CheckStatus.FAIL


# ---------------------------------------------------------------------------
# Constraint checks
# ---------------------------------------------------------------------------


class TestPreflightConstraintChecks:
    def _run(self, **overrides: object) -> PreflightReport:
        return LivePilotPreflightChecker(_full_settings(**overrides)).run()

    def test_quantity_one_passes(self):
        report = self._run(live_max_order_quantity=1)
        c = next(c for c in report.checks if c.name == "LIVE_MAX_ORDER_QUANTITY")
        assert c.status == CheckStatus.PASS

    def test_quantity_high_warns(self):
        report = self._run(live_max_order_quantity=100)
        c = next(c for c in report.checks if c.name == "LIVE_MAX_ORDER_QUANTITY")
        assert c.status == CheckStatus.WARN

    def test_quantity_zero_fails(self):
        report = self._run(live_max_order_quantity=0)
        c = next(c for c in report.checks if c.name == "LIVE_MAX_ORDER_QUANTITY")
        assert c.status == CheckStatus.FAIL

    def test_empty_symbols_fails(self):
        report = self._run(live_allowed_symbols=[])
        c = next(c for c in report.checks if c.name == "LIVE_ALLOWED_SYMBOLS")
        assert c.status == CheckStatus.FAIL
        assert c.level == CheckLevel.REQUIRED

    def test_symbols_set_passes(self):
        report = self._run(live_allowed_symbols=["RELIANCE"])
        c = next(c for c in report.checks if c.name == "LIVE_ALLOWED_SYMBOLS")
        assert c.status == CheckStatus.PASS

    def test_non_mis_product_warns(self):
        report = self._run(live_allowed_product="CNC")
        c = next(c for c in report.checks if c.name == "LIVE_ALLOWED_PRODUCT")
        assert c.status == CheckStatus.WARN

    def test_mis_product_passes(self):
        report = self._run(live_allowed_product="MIS")
        c = next(c for c in report.checks if c.name == "LIVE_ALLOWED_PRODUCT")
        assert c.status == CheckStatus.PASS

    def test_non_nse_exchange_warns(self):
        report = self._run(live_allowed_exchange="BSE")
        c = next(c for c in report.checks if c.name == "LIVE_ALLOWED_EXCHANGE")
        assert c.status == CheckStatus.WARN

    def test_order_types_standard_passes(self):
        report = self._run(live_allowed_order_types=["MARKET", "LIMIT"])
        c = next(c for c in report.checks if c.name == "LIVE_ALLOWED_ORDER_TYPES")
        assert c.status == CheckStatus.PASS

    def test_order_types_non_standard_warns(self):
        report = self._run(live_allowed_order_types=["MARKET", "SL"])
        c = next(c for c in report.checks if c.name == "LIVE_ALLOWED_ORDER_TYPES")
        assert c.status == CheckStatus.WARN

    def test_empty_order_types_fails(self):
        report = self._run(live_allowed_order_types=[])
        c = next(c for c in report.checks if c.name == "LIVE_ALLOWED_ORDER_TYPES")
        assert c.status == CheckStatus.FAIL


# ---------------------------------------------------------------------------
# Credential checks — never reveal values
# ---------------------------------------------------------------------------


class TestPreflightCredentialChecks:
    def _run(self, **overrides: object) -> PreflightReport:
        return LivePilotPreflightChecker(_full_settings(**overrides)).run()

    def test_all_credentials_present_passes(self):
        report = self._run()
        for name in ("ZERODHA_API_KEY", "ZERODHA_API_SECRET", "ZERODHA_ACCESS_TOKEN"):
            c = next(c for c in report.checks if c.name == name)
            assert c.status == CheckStatus.PASS

    def test_missing_api_key_fails(self):
        report = self._run(zerodha_api_key=_Secret(""))
        c = next(c for c in report.checks if c.name == "ZERODHA_API_KEY")
        assert c.status == CheckStatus.FAIL

    def test_credentials_not_in_output(self):
        """Credential values must never appear in check messages or details."""
        report = self._run(
            zerodha_api_key=_Secret("SUPER_SECRET_KEY_XYZ"),
            zerodha_api_secret=_Secret("SUPER_SECRET_VALUE_ABC"),
            zerodha_access_token=_Secret("SUPER_SECRET_TOKEN_123"),
        )
        full_output = json.dumps(report.to_dict())
        assert "SUPER_SECRET_KEY_XYZ" not in full_output
        assert "SUPER_SECRET_VALUE_ABC" not in full_output
        assert "SUPER_SECRET_TOKEN_123" not in full_output

    def test_summary_does_not_contain_credentials(self):
        report = self._run(
            zerodha_api_key=_Secret("MY_VERY_SECRET_API_KEY"),
        )
        assert "MY_VERY_SECRET_API_KEY" not in report.summary()


# ---------------------------------------------------------------------------
# Kill switch check
# ---------------------------------------------------------------------------


class TestPreflightKillSwitch:
    def test_no_kill_switch_warns(self):
        checker = LivePilotPreflightChecker(_full_settings(), kill_switch=None)
        report = checker.run()
        c = next(c for c in report.checks if c.name == "KILL_SWITCH")
        assert c.status == CheckStatus.WARN

    def test_inactive_kill_switch_passes(self):
        checker = LivePilotPreflightChecker(
            _full_settings(), kill_switch=_FakeKillSwitch(active=False)
        )
        report = checker.run()
        c = next(c for c in report.checks if c.name == "KILL_SWITCH")
        assert c.status == CheckStatus.PASS

    def test_active_kill_switch_fails(self):
        checker = LivePilotPreflightChecker(
            _full_settings(), kill_switch=_FakeKillSwitch(active=True, reason="test stop")
        )
        report = checker.run()
        c = next(c for c in report.checks if c.name == "KILL_SWITCH")
        assert c.status == CheckStatus.FAIL
        assert c.level == CheckLevel.REQUIRED

    def test_active_kill_switch_blocks_overall_pass(self):
        checker = LivePilotPreflightChecker(
            _full_settings(), kill_switch=_FakeKillSwitch(active=True)
        )
        report = checker.run()
        assert report.passed is False


# ---------------------------------------------------------------------------
# Static IP advisory
# ---------------------------------------------------------------------------


class TestPreflightStaticIP:
    def test_static_ip_is_advisory_by_default(self):
        checker = LivePilotPreflightChecker(_full_settings())
        report = checker.run()
        c = next(c for c in report.checks if c.name == "STATIC_IP_CONFIRMED")
        assert c.level == CheckLevel.ADVISORY

    def test_static_ip_required_when_flag_set(self):
        checker = LivePilotPreflightChecker(_full_settings(), require_static_ip=True)
        report = checker.run()
        c = next(c for c in report.checks if c.name == "STATIC_IP_CONFIRMED")
        assert c.level == CheckLevel.REQUIRED

    def test_static_ip_warn_does_not_fail_report(self):
        checker = LivePilotPreflightChecker(
            _full_settings(), kill_switch=_FakeKillSwitch(active=False)
        )
        report = checker.run()
        assert report.passed is True  # WARN on ADVISORY should not fail

    def test_static_ip_required_fails_report(self):
        checker = LivePilotPreflightChecker(
            _full_settings(), require_static_ip=True, kill_switch=_FakeKillSwitch(active=False)
        )
        report = checker.run()
        # STATIC_IP_CONFIRMED is WARN but level is REQUIRED — report should fail
        c = next(c for c in report.checks if c.name == "STATIC_IP_CONFIRMED")
        assert c.level == CheckLevel.REQUIRED
        assert c.status == CheckStatus.WARN
        # WARN on a REQUIRED check should still cause report.passed to be False
        assert report.passed is False


# ---------------------------------------------------------------------------
# Filesystem checks
# ---------------------------------------------------------------------------


class TestPreflightFilesystem:
    def test_writable_audit_dir_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = LivePilotPreflightChecker(
                _full_settings(),
                audit_log_path=Path(tmpdir) / "audit.jsonl",
            )
            report = checker.run()
            c = next(c for c in report.checks if c.name == "AUDIT_LOG_WRITABLE")
            assert c.status == CheckStatus.PASS

    def test_dashboard_path_check_included_when_provided(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = LivePilotPreflightChecker(
                _full_settings(),
                dashboard_path=Path(tmpdir) / "status.json",
            )
            report = checker.run()
            names = [c.name for c in report.checks]
            assert "DASHBOARD_PATH_WRITABLE" in names


# ---------------------------------------------------------------------------
# Disabled defaults
# ---------------------------------------------------------------------------


class TestPreflightDisabledDefaults:
    def test_all_flags_disabled_fails(self):
        checker = LivePilotPreflightChecker(_disabled_settings())
        report = checker.run()
        assert report.passed is False

    def test_disabled_report_shows_failures(self):
        checker = LivePilotPreflightChecker(_disabled_settings())
        report = checker.run()
        assert len(report.required_failures) > 0

    def test_empty_symbols_blocks_pilot(self):
        checker = LivePilotPreflightChecker(_disabled_settings())
        report = checker.run()
        c = next(c for c in report.checks if c.name == "LIVE_ALLOWED_SYMBOLS")
        assert c.status == CheckStatus.FAIL
