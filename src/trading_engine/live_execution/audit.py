"""Approval audit logger.

ApprovalAuditLogger writes JSON-lines records to a file for every approval
request, decision, and dry-run preview.  Each line is a valid JSON object.

No secrets are logged.  No database is required.  Parent directories are
created automatically.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from trading_engine.live_execution.dry_run import DryRunOrderPreview
    from trading_engine.live_execution.models import ApprovalDecision, ApprovalRequest


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


class ApprovalAuditLogger:
    """Writes JSONL audit records to a file.

    Each call to log_request, log_decision, or log_dry_run appends one
    newline-terminated JSON object to the audit file.

    Args:
        log_path: Path to the audit file.  Parent directories are created.

    Example:
        logger = ApprovalAuditLogger("data/audit/approvals.jsonl")
        logger.log_request(request)
        logger.log_decision(decision)
    """

    def __init__(self, log_path: str | Path) -> None:
        self._path = Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_request(self, request: ApprovalRequest) -> None:
        """Append a JSON-line record for an ApprovalRequest."""
        record: dict[str, Any] = {
            "event": "approval_request",
            "logged_at": _utc_now_iso(),
            **request.to_dict(),
        }
        self._append(record)

    def log_decision(self, decision: ApprovalDecision) -> None:
        """Append a JSON-line record for an ApprovalDecision."""
        record: dict[str, Any] = {
            "event": "approval_decision",
            "logged_at": _utc_now_iso(),
            **decision.to_dict(),
        }
        self._append(record)

    def log_dry_run(self, preview: DryRunOrderPreview) -> None:
        """Append a JSON-line record for a DryRunOrderPreview."""
        record: dict[str, Any] = {
            "event": "dry_run_preview",
            "logged_at": _utc_now_iso(),
            **preview.to_dict(),
        }
        self._append(record)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _append(self, record: dict[str, Any]) -> None:
        try:
            line = json.dumps(record, ensure_ascii=False)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            self._logger.exception("ApprovalAuditLogger: failed to write record.")
