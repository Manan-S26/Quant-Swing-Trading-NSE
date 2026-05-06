"""Tests for structured JSON logging."""

from __future__ import annotations

import json
import logging

import pytest

from trading_engine.common.logging import StructuredJsonFormatter, get_logger


def make_log_record(
    msg: str,
    level: int = logging.INFO,
    name: str = "test.module",
    **extra: object,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, val in extra.items():
        setattr(record, key, val)
    return record


class TestStructuredJsonFormatter:
    def setup_method(self) -> None:
        self.formatter = StructuredJsonFormatter()

    def _parse(self, record: logging.LogRecord) -> dict:
        return json.loads(self.formatter.format(record))

    def test_output_is_valid_json(self) -> None:
        record = make_log_record("hello world")
        output = self.formatter.format(record)
        parsed = json.loads(output)  # must not raise
        assert isinstance(parsed, dict)

    def test_required_fields_present(self) -> None:
        record = make_log_record("test message")
        parsed = self._parse(record)
        assert "timestamp" in parsed
        assert "level" in parsed
        assert "module" in parsed
        assert "message" in parsed

    def test_message_content(self) -> None:
        record = make_log_record("order placed")
        parsed = self._parse(record)
        assert parsed["message"] == "order placed"

    def test_level_name(self) -> None:
        record = make_log_record("warn msg", level=logging.WARNING)
        parsed = self._parse(record)
        assert parsed["level"] == "WARNING"

    def test_module_name(self) -> None:
        record = make_log_record("msg", name="trading_engine.risk.engine")
        parsed = self._parse(record)
        assert parsed["module"] == "trading_engine.risk.engine"

    def test_timestamp_is_iso_format(self) -> None:
        record = make_log_record("ts test")
        parsed = self._parse(record)
        # Should parse without error
        from datetime import datetime
        datetime.fromisoformat(parsed["timestamp"])

    def test_extra_context_included(self) -> None:
        record = make_log_record("msg with context", strategy_id="orb_v1")
        parsed = self._parse(record)
        assert "context" in parsed
        assert parsed["context"]["strategy_id"] == "orb_v1"

    def test_secret_key_redacted_in_context(self) -> None:
        record = make_log_record("msg", api_key="SHOULD_BE_HIDDEN")
        parsed = self._parse(record)
        context = parsed.get("context", {})
        assert "SHOULD_BE_HIDDEN" not in json.dumps(context)
        assert context.get("api_key") == "***REDACTED***"

    def test_password_redacted_in_context(self) -> None:
        record = make_log_record("msg", password="hunter2")
        parsed = self._parse(record)
        context = parsed.get("context", {})
        assert "hunter2" not in json.dumps(context)

    def test_token_redacted_in_context(self) -> None:
        record = make_log_record("msg", access_token="tok123")
        parsed = self._parse(record)
        context = parsed.get("context", {})
        assert "tok123" not in json.dumps(context)

    def test_non_sensitive_context_passes_through(self) -> None:
        record = make_log_record("msg", symbol="RELIANCE", quantity=10)
        parsed = self._parse(record)
        assert parsed["context"]["symbol"] == "RELIANCE"
        assert parsed["context"]["quantity"] == 10


class TestGetLogger:
    def test_returns_logger(self) -> None:
        logger = get_logger("trading_engine.test")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "trading_engine.test"
