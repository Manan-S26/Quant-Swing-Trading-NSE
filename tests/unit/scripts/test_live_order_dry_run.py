"""Tests for scripts/live_order_dry_run.py — CLI dry-run tool."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure scripts/ is importable before importing the script module.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import live_order_dry_run as _script  # noqa: E402


class TestArgParsing:
    def test_required_args_parsed(self):
        args = _script._parse_args(
            ["--symbol", "RELIANCE", "--side", "BUY", "--quantity", "1", "--order-type", "MARKET"]
        )
        assert args.symbol == "RELIANCE"
        assert args.side == "BUY"
        assert args.quantity == 1
        assert args.order_type == "MARKET"

    def test_defaults(self):
        args = _script._parse_args(
            ["--symbol", "RELIANCE", "--side", "BUY", "--quantity", "1", "--order-type", "MARKET"]
        )
        assert args.product == "MIS"
        assert args.strategy_id == "manual_dry_run"
        assert args.exchange == "NSE"

    def test_optional_price(self):
        args = _script._parse_args(
            [
                "--symbol",
                "RELIANCE",
                "--side",
                "BUY",
                "--quantity",
                "1",
                "--order-type",
                "LIMIT",
                "--price",
                "2345",
            ]
        )
        assert args.price == "2345"


class TestBuildIntent:
    def test_market_order_intent_built(self):
        args = _script._parse_args(
            ["--symbol", "RELIANCE", "--side", "BUY", "--quantity", "2", "--order-type", "MARKET"]
        )
        intent = _script._build_intent(args)
        assert intent.symbol == "RELIANCE"
        assert intent.quantity == 2
        assert intent.order_type == "MARKET"

    def test_limit_order_requires_price(self):
        args = _script._parse_args(
            ["--symbol", "RELIANCE", "--side", "BUY", "--quantity", "1", "--order-type", "LIMIT"]
        )
        with pytest.raises(SystemExit):
            _script._build_intent(args)

    def test_invalid_quantity_exits(self):
        args = _script._parse_args(
            ["--symbol", "RELIANCE", "--side", "BUY", "--quantity", "-1", "--order-type", "MARKET"]
        )
        with pytest.raises(SystemExit):
            _script._build_intent(args)

    def test_invalid_price_exits(self):
        args = _script._parse_args(
            [
                "--symbol",
                "RELIANCE",
                "--side",
                "BUY",
                "--quantity",
                "1",
                "--order-type",
                "LIMIT",
                "--price",
                "not_a_number",
            ]
        )
        with pytest.raises(SystemExit):
            _script._build_intent(args)

    def test_zero_price_exits(self):
        args = _script._parse_args(
            [
                "--symbol",
                "RELIANCE",
                "--side",
                "BUY",
                "--quantity",
                "1",
                "--order-type",
                "LIMIT",
                "--price",
                "0",
            ]
        )
        with pytest.raises(SystemExit):
            _script._build_intent(args)


class TestMain:
    def test_main_returns_0(self, capsys):
        rc = _script.main(
            ["--symbol", "RELIANCE", "--side", "BUY", "--quantity", "1", "--order-type", "MARKET"]
        )
        assert rc == 0

    def test_main_prints_json(self, capsys):
        _script.main(
            ["--symbol", "RELIANCE", "--side", "BUY", "--quantity", "1", "--order-type", "MARKET"]
        )
        captured = capsys.readouterr()
        # Output should be valid JSON.
        obj = json.loads(captured.out)
        assert obj["symbol"] == "RELIANCE"

    def test_main_no_zerodha_calls(self, capsys):
        # This test verifies the script completes without credentials.
        # If any Zerodha API call were made it would raise ImportError or ConnectionError.
        _script.main(
            ["--symbol", "INFY", "--side", "SELL", "--quantity", "5", "--order-type", "MARKET"]
        )
        captured = capsys.readouterr()
        obj = json.loads(captured.out)
        assert obj["symbol"] == "INFY"

    def test_output_contains_approval_status(self, capsys):
        _script.main(
            ["--symbol", "RELIANCE", "--side", "BUY", "--quantity", "1", "--order-type", "MARKET"]
        )
        captured = capsys.readouterr()
        obj = json.loads(captured.out)
        assert "approval_status" in obj

    def test_output_contains_message(self, capsys):
        _script.main(
            ["--symbol", "RELIANCE", "--side", "BUY", "--quantity", "1", "--order-type", "MARKET"]
        )
        captured = capsys.readouterr()
        obj = json.loads(captured.out)
        assert "message" in obj
        assert "DRY RUN" in obj["message"]

    def test_limit_order_with_price(self, capsys):
        rc = _script.main(
            [
                "--symbol",
                "RELIANCE",
                "--side",
                "BUY",
                "--quantity",
                "1",
                "--order-type",
                "LIMIT",
                "--price",
                "2300",
            ]
        )
        assert rc == 0
        obj = json.loads(capsys.readouterr().out)
        assert obj["estimated_price"] == "2300"
