"""Structured JSON logging for the trading engine.

Every log record is emitted as a JSON line with:
  timestamp, level, module, message, and optional context.

Sensitive field names (containing "secret", "password", "token", "key")
are automatically redacted in context payloads.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

# Fields that exist on every LogRecord — excluded from context extraction.
_LOGRECORD_BUILTIN_ATTRS: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "id",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

_REDACT_SUBSTRINGS: frozenset[str] = frozenset(
    {"secret", "password", "token", "api_key", "apikey", "credential"}
)


def _is_sensitive(key: str) -> bool:
    lower = key.lower()
    return any(s in lower for s in _REDACT_SUBSTRINGS)


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Attach extra context fields added via logger.info("msg", extra={"key": val})
        context: dict[str, Any] = {}
        for key, val in record.__dict__.items():
            if key in _LOGRECORD_BUILTIN_ATTRS or key.startswith("_"):
                continue
            context[key] = "***REDACTED***" if _is_sensitive(key) else val

        if context:
            payload["context"] = context

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Configure structured JSON logging engine-wide.

    Call once at application startup before creating any loggers.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredJsonFormatter())
    root = logging.getLogger()
    root.setLevel(numeric_level)
    root.handlers.clear()
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Use __name__ as the name in each module."""
    return logging.getLogger(name)
