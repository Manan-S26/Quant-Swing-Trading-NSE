"""Tests for DashboardSession model."""

from __future__ import annotations

from datetime import datetime

import pytest

from trading_engine.dashboard.models import DashboardSession

_TS = datetime(2024, 1, 15, 9, 30, 0)
_STATUS = {"total_orders": 5, "orders_by_status": {"FILLED": 3, "OPEN": 2}}


class TestDashboardSessionToDict:
    def test_to_dict_contains_all_fields(self):
        session = DashboardSession(generated_at=_TS, status=_STATUS)
        d = session.to_dict()
        assert "generated_at" in d
        assert "status" in d
        assert "source" in d
        assert "version" in d

    def test_generated_at_serialized_as_iso(self):
        session = DashboardSession(generated_at=_TS, status=_STATUS)
        d = session.to_dict()
        assert d["generated_at"] == _TS.isoformat()

    def test_status_preserved(self):
        session = DashboardSession(generated_at=_TS, status=_STATUS)
        assert session.to_dict()["status"] == _STATUS

    def test_defaults(self):
        session = DashboardSession(generated_at=_TS, status={})
        d = session.to_dict()
        assert d["source"] == "local"
        assert d["version"] == "1"

    def test_custom_source_and_version(self):
        session = DashboardSession(generated_at=_TS, status={}, source="paper", version="2")
        d = session.to_dict()
        assert d["source"] == "paper"
        assert d["version"] == "2"


class TestDashboardSessionFromDict:
    def test_roundtrip(self):
        session = DashboardSession(generated_at=_TS, status=_STATUS, source="paper")
        restored = DashboardSession.from_dict(session.to_dict())
        assert restored.generated_at == _TS
        assert restored.status == _STATUS
        assert restored.source == "paper"
        assert restored.version == "1"

    def test_missing_generated_at_defaults_to_now(self):
        data = {"status": _STATUS}
        session = DashboardSession.from_dict(data)
        assert isinstance(session.generated_at, datetime)

    def test_missing_status_defaults_to_empty_dict(self):
        session = DashboardSession.from_dict({"generated_at": _TS.isoformat()})
        assert session.status == {}

    def test_missing_source_defaults_to_local(self):
        session = DashboardSession.from_dict({"generated_at": _TS.isoformat()})
        assert session.source == "local"

    def test_missing_version_defaults_to_one(self):
        session = DashboardSession.from_dict({"generated_at": _TS.isoformat()})
        assert session.version == "1"

    def test_empty_dict(self):
        session = DashboardSession.from_dict({})
        assert session.status == {}
        assert session.source == "local"

    def test_bad_timestamp_raises_value_error(self):
        with pytest.raises(ValueError):
            DashboardSession.from_dict({"generated_at": "not-a-date"})

    def test_nested_status_preserved(self):
        data = {
            "generated_at": _TS.isoformat(),
            "status": {"orders_by_status": {"FILLED": 5}, "total_orders": 5},
        }
        session = DashboardSession.from_dict(data)
        assert session.status["orders_by_status"]["FILLED"] == 5
