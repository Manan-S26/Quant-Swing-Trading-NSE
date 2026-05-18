"""Dashboard session data model.

DashboardSession is the JSON-serialisable envelope that wraps a StatusPage
snapshot.  It adds metadata (generated_at, source, version) that the
Streamlit dashboard uses for display and freshness checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class DashboardSession:
    """A single snapshot written to the dashboard JSON file.

    Attributes:
        generated_at: When the snapshot was captured (ISO string when serialised).
        status:       The raw StatusPage.to_dict() payload.
        source:       Where the snapshot originated (e.g. "local", "paper", "backtest").
        version:      Simple schema version string for forward-compatibility checks.
    """

    generated_at: datetime
    status: dict[str, Any]
    source: str = "local"
    version: str = "1"

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "generated_at": self.generated_at.isoformat(),
            "status": self.status,
            "source": self.source,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DashboardSession:
        """Reconstruct a DashboardSession from a plain dict.

        Tolerates missing optional fields by falling back to defaults.

        Args:
            data: A dict as produced by to_dict() or read from a JSON file.

        Returns:
            DashboardSession populated from data.

        Raises:
            ValueError: if generated_at is present but unparseable.
        """
        raw_ts = data.get("generated_at")
        if raw_ts:
            try:
                generated_at = datetime.fromisoformat(str(raw_ts))
            except ValueError as exc:
                raise ValueError(
                    f"Cannot parse generated_at={raw_ts!r} as ISO datetime: {exc}"
                ) from exc
        else:
            generated_at = datetime.now()

        return cls(
            generated_at=generated_at,
            status=data.get("status") or {},
            source=data.get("source", "local"),
            version=str(data.get("version", "1")),
        )
