"""Dashboard session file writer.

Writes StatusPage snapshots to a JSON file using an atomic replace pattern
so that the Streamlit dashboard never reads a partially-written file.

Usage::

    writer = DashboardSessionWriter("data/dashboard/session_status.json")
    writer.write_status(status_page.to_dict(), source="paper")

    session = writer.read_status()   # DashboardSession | None
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from trading_engine.dashboard.models import DashboardSession

logger = logging.getLogger(__name__)


class DashboardSessionWriter:
    """Atomic JSON writer/reader for dashboard session snapshots.

    Args:
        output_path: Destination file path (created with parent dirs if needed).
    """

    def __init__(self, output_path: str | Path) -> None:
        self._path = Path(output_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write_status(
        self,
        status: dict[str, Any],
        source: str = "local",
    ) -> Path:
        """Write a StatusPage dict snapshot to the session JSON file.

        Uses an atomic write: writes to a sibling temp file, then renames
        it to the final path to avoid partial reads.

        Args:
            status: The dict returned by StatusPage.to_dict().
            source: Where this snapshot originated (e.g. "local", "paper").

        Returns:
            The path the file was written to.
        """
        session = DashboardSession(
            generated_at=datetime.now(),
            status=status,
            source=source,
        )
        payload = json.dumps(session.to_dict(), indent=2, ensure_ascii=False)

        # Ensure parent directory exists.
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: temp file in same directory → rename.
        fd, tmp_path = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=".dashboard_tmp_",
            suffix=".json",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp_path, self._path)
        except Exception:
            # Clean up temp file on failure.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.debug("DashboardSessionWriter: wrote session to %s", self._path)
        return self._path

    def read_status(self) -> DashboardSession | None:
        """Read and parse the session JSON file.

        Returns:
            DashboardSession if the file exists and parses cleanly, else None.
        """
        if not self._path.exists():
            return None
        try:
            text = self._path.read_text(encoding="utf-8")
            data = json.loads(text)
            return DashboardSession.from_dict(data)
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            logger.warning("DashboardSessionWriter: could not read %s: %s", self._path, exc)
            return None

    def exists(self) -> bool:
        """Return True if the session file exists."""
        return self._path.exists()
