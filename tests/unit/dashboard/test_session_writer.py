"""Tests for DashboardSessionWriter."""

from __future__ import annotations

import json
from pathlib import Path

from trading_engine.dashboard.models import DashboardSession
from trading_engine.dashboard.session_writer import DashboardSessionWriter

_STATUS = {
    "total_orders": 3,
    "total_fills": 1,
    "total_risk_decisions": 3,
    "open_positions_count": 0,
    "orders_by_status": {"FILLED": 1, "RISK_APPROVED": 2},
    "last_reconciliation_timestamp": None,
    "last_reconciliation_success": None,
    "discrepancy_count": 0,
}


class TestDashboardSessionWriterWrite:
    def test_write_creates_file(self, tmp_path: Path):
        output = tmp_path / "session.json"
        writer = DashboardSessionWriter(output)
        writer.write_status(_STATUS)
        assert output.exists()

    def test_write_returns_path(self, tmp_path: Path):
        output = tmp_path / "session.json"
        writer = DashboardSessionWriter(output)
        returned = writer.write_status(_STATUS)
        assert returned == output

    def test_write_creates_parent_directories(self, tmp_path: Path):
        output = tmp_path / "deep" / "nested" / "session.json"
        writer = DashboardSessionWriter(output)
        writer.write_status(_STATUS)
        assert output.exists()

    def test_written_json_is_valid(self, tmp_path: Path):
        output = tmp_path / "session.json"
        DashboardSessionWriter(output).write_status(_STATUS)
        data = json.loads(output.read_text())
        assert "generated_at" in data
        assert "status" in data

    def test_written_status_matches_input(self, tmp_path: Path):
        output = tmp_path / "session.json"
        DashboardSessionWriter(output).write_status(_STATUS)
        data = json.loads(output.read_text())
        assert data["status"] == _STATUS

    def test_source_written(self, tmp_path: Path):
        output = tmp_path / "session.json"
        DashboardSessionWriter(output).write_status(_STATUS, source="paper")
        data = json.loads(output.read_text())
        assert data["source"] == "paper"

    def test_default_source_is_local(self, tmp_path: Path):
        output = tmp_path / "session.json"
        DashboardSessionWriter(output).write_status(_STATUS)
        data = json.loads(output.read_text())
        assert data["source"] == "local"

    def test_overwrite_updates_content(self, tmp_path: Path):
        output = tmp_path / "session.json"
        writer = DashboardSessionWriter(output)
        writer.write_status({"total_orders": 1})
        writer.write_status({"total_orders": 99})
        data = json.loads(output.read_text())
        assert data["status"]["total_orders"] == 99


class TestDashboardSessionWriterRead:
    def test_read_returns_dashboard_session(self, tmp_path: Path):
        output = tmp_path / "session.json"
        writer = DashboardSessionWriter(output)
        writer.write_status(_STATUS)
        session = writer.read_status()
        assert isinstance(session, DashboardSession)

    def test_read_status_matches_written(self, tmp_path: Path):
        output = tmp_path / "session.json"
        writer = DashboardSessionWriter(output)
        writer.write_status(_STATUS)
        session = writer.read_status()
        assert session is not None
        assert session.status == _STATUS

    def test_read_missing_file_returns_none(self, tmp_path: Path):
        output = tmp_path / "nonexistent.json"
        writer = DashboardSessionWriter(output)
        assert writer.read_status() is None

    def test_read_malformed_json_returns_none(self, tmp_path: Path):
        output = tmp_path / "session.json"
        output.write_text("this is not json", encoding="utf-8")
        writer = DashboardSessionWriter(output)
        assert writer.read_status() is None

    def test_read_empty_json_object_returns_session(self, tmp_path: Path):
        output = tmp_path / "session.json"
        output.write_text("{}", encoding="utf-8")
        session = DashboardSessionWriter(output).read_status()
        assert isinstance(session, DashboardSession)
        assert session.status == {}


class TestDashboardSessionWriterExists:
    def test_exists_false_when_no_file(self, tmp_path: Path):
        writer = DashboardSessionWriter(tmp_path / "session.json")
        assert writer.exists() is False

    def test_exists_true_after_write(self, tmp_path: Path):
        output = tmp_path / "session.json"
        writer = DashboardSessionWriter(output)
        writer.write_status(_STATUS)
        assert writer.exists() is True

    def test_exists_false_after_delete(self, tmp_path: Path):
        output = tmp_path / "session.json"
        writer = DashboardSessionWriter(output)
        writer.write_status(_STATUS)
        output.unlink()
        assert writer.exists() is False


class TestNoSecretsWritten:
    def test_normal_status_written_without_secrets(self, tmp_path: Path):
        output = tmp_path / "session.json"
        DashboardSessionWriter(output).write_status(_STATUS)
        content = output.read_text()
        # No secret-looking fields in a normal status dict
        for bad_word in ("password", "secret", "api_key", "access_token"):
            assert bad_word not in content.lower()
