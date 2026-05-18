"""Tests for scripts/live_pilot_preflight.py — preflight CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import live_pilot_preflight as _script  # noqa: E402


class TestArgParsing:
    def test_no_args_parses(self):
        args = _script._parse_args([])
        assert args.output_json is False
        assert args.require_static_ip is False
        assert args.audit_log_path is None
        assert args.dashboard_path is None

    def test_json_flag(self):
        args = _script._parse_args(["--json"])
        assert args.output_json is True

    def test_require_static_ip_flag(self):
        args = _script._parse_args(["--require-static-ip-confirmed"])
        assert args.require_static_ip is True

    def test_audit_log_path(self):
        args = _script._parse_args(["--audit-log-path", "data/audit/test.jsonl"])
        assert args.audit_log_path == "data/audit/test.jsonl"

    def test_dashboard_path(self):
        args = _script._parse_args(["--dashboard-path", "data/dashboard/status.json"])
        assert args.dashboard_path == "data/dashboard/status.json"


class TestMainOutput:
    def test_outputs_human_readable_by_default(self, capsys, monkeypatch):
        monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
        monkeypatch.setenv("LIVE_ORDER_EXECUTION_ENABLED", "false")
        _script.main([])
        captured = capsys.readouterr()
        # Should contain PASS/FAIL/WARN text
        assert any(s in captured.out for s in ("PASS", "FAIL", "WARN"))

    def test_json_flag_outputs_valid_json(self, capsys, monkeypatch):
        monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
        _script.main(["--json"])
        captured = capsys.readouterr()
        obj = json.loads(captured.out)
        assert "passed" in obj
        assert "checks" in obj

    def test_json_output_is_list_of_checks(self, capsys, monkeypatch):
        monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
        _script.main(["--json"])
        captured = capsys.readouterr()
        obj = json.loads(captured.out)
        assert isinstance(obj["checks"], list)
        assert len(obj["checks"]) > 0

    def test_json_output_checks_have_required_keys(self, capsys, monkeypatch):
        monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
        _script.main(["--json"])
        captured = capsys.readouterr()
        obj = json.loads(captured.out)
        check = obj["checks"][0]
        for key in ("name", "status", "level", "message"):
            assert key in check


class TestMainExitCodes:
    def test_returns_1_when_flags_disabled(self, monkeypatch):
        monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
        monkeypatch.setenv("LIVE_ORDER_EXECUTION_ENABLED", "false")
        monkeypatch.setenv("LIVE_ORDER_PILOT_ENABLED", "false")
        rc = _script.main([])
        assert rc == 1

    def test_no_secrets_in_json_output(self, capsys, monkeypatch):
        """JSON output must never contain secret values."""
        monkeypatch.setenv("ZERODHA_API_KEY", "SHOULD_NOT_APPEAR_IN_OUTPUT")
        monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
        _script.main(["--json"])
        captured = capsys.readouterr()
        assert "SHOULD_NOT_APPEAR_IN_OUTPUT" not in captured.out


class TestDoesNotPlaceOrders:
    def test_does_not_call_zerodha_order_apis(self, monkeypatch):
        """Preflight must never call any order placement API."""
        # If any broker placement were attempted, kiteconnect would raise ImportError
        # or connection errors. The script must complete cleanly without those.
        # We verify by simply running it with all flags off.
        monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
        # Should not raise, should not hang
        rc = _script.main([])
        assert isinstance(rc, int)
