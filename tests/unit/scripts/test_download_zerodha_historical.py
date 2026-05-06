"""Tests for Zerodha historical data download logic.

All tests use fake brokers and fake data — no real Zerodha API calls.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from trading_engine.data.universe import UniverseConfig
from trading_engine.data.zerodha_downloader import (
    DownloadConfig,
    DownloadResult,
    assert_live_trading_disabled,
    build_instrument_map,
    run_download,
)

# ---------------------------------------------------------------------------
# Fake instruments list
# ---------------------------------------------------------------------------

_FAKE_INSTRUMENTS = [
    {"tradingsymbol": "RELIANCE", "instrument_token": 738561, "exchange": "NSE"},
    {"tradingsymbol": "TCS", "instrument_token": 2953217, "exchange": "NSE"},
    {"tradingsymbol": "INFY", "instrument_token": 408065, "exchange": "NSE"},
]

_FAKE_CANDLES = [
    {
        "date": "2024-01-15 09:30:00",
        "open": 2800.0,
        "high": 2820.0,
        "low": 2790.0,
        "close": 2810.0,
        "volume": 50000,
    }
]


# ---------------------------------------------------------------------------
# Fake settings
# ---------------------------------------------------------------------------


class _FakeSettings:
    live_trading_enabled = False
    zerodha_api_key = MagicMock(get_secret_value=lambda: "fake_key")
    zerodha_api_secret = MagicMock(get_secret_value=lambda: "fake_secret")
    zerodha_access_token = MagicMock(get_secret_value=lambda: "fake_token")
    data_dir = "./data"
    historical_interval = "5minute"
    historical_from_date = ""
    historical_to_date = ""


class _LiveSettings(_FakeSettings):
    live_trading_enabled = True


# ---------------------------------------------------------------------------
# Fake broker
# ---------------------------------------------------------------------------


class _FakeBroker:
    def __init__(self, candles: list[dict] | None = None) -> None:
        self._candles = candles or _FAKE_CANDLES
        self.get_historical_data_calls: list[dict[str, Any]] = []
        self.get_instruments_calls: int = 0

    def get_instruments(self, exchange: str) -> list[dict[str, Any]]:
        self.get_instruments_calls += 1
        return _FAKE_INSTRUMENTS

    def get_historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
    ) -> list[dict[str, Any]]:
        self.get_historical_data_calls.append(
            {"token": instrument_token, "from": from_date, "to": to_date, "interval": interval}
        )
        return self._candles


# ---------------------------------------------------------------------------
# Universe fixture
# ---------------------------------------------------------------------------


def _make_universe(symbols: list[str] | None = None) -> UniverseConfig:
    return UniverseConfig(
        name="test",
        exchange="NSE",
        symbols=symbols or ["RELIANCE", "TCS"],
    )


def _make_config(
    universe: UniverseConfig | None = None,
    symbols: list[str] | None = None,
    dry_run: bool = False,
    tmp_path: Path | None = None,
) -> DownloadConfig:
    return DownloadConfig(
        universe=universe or _make_universe(),
        interval="5minute",
        from_date=datetime(2024, 1, 15),
        to_date=datetime(2024, 1, 15),
        data_dir=str(tmp_path or "./data"),
        symbols=symbols or [],
        dry_run=dry_run,
        save=False,  # don't write real files in unit tests
    )


# ---------------------------------------------------------------------------
# Tests: safety guard
# ---------------------------------------------------------------------------


class TestAssertLiveTradingDisabled:
    def test_passes_when_disabled(self):
        assert_live_trading_disabled(_FakeSettings())  # should not raise

    def test_raises_when_enabled(self):
        with pytest.raises(SystemExit):
            assert_live_trading_disabled(_LiveSettings())

    def test_exit_message_mentions_safety(self):
        with pytest.raises(SystemExit) as exc_info:
            assert_live_trading_disabled(_LiveSettings())
        assert "SAFETY" in str(exc_info.value) or "LIVE_TRADING_ENABLED" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Tests: instrument map
# ---------------------------------------------------------------------------


class TestBuildInstrumentMap:
    def test_found_symbol_returns_correct_token(self):
        found, missing = build_instrument_map(_FAKE_INSTRUMENTS, ["RELIANCE", "TCS"])
        assert found["RELIANCE"] == 738561
        assert found["TCS"] == 2953217
        assert missing == []

    def test_missing_symbol_reported(self):
        found, missing = build_instrument_map(_FAKE_INSTRUMENTS, ["RELIANCE", "UNKNOWN"])
        assert "RELIANCE" in found
        assert "UNKNOWN" in missing
        assert "UNKNOWN" not in found

    def test_empty_symbols_list_returns_empty(self):
        found, missing = build_instrument_map(_FAKE_INSTRUMENTS, [])
        assert found == {}
        assert missing == []

    def test_empty_instruments_returns_all_missing(self):
        found, missing = build_instrument_map([], ["RELIANCE", "TCS"])
        assert found == {}
        assert set(missing) == {"RELIANCE", "TCS"}

    def test_exchange_filter_applied(self):
        instruments = [
            {"tradingsymbol": "RELIANCE", "instrument_token": 1, "exchange": "NSE"},
            {"tradingsymbol": "RELIANCE", "instrument_token": 2, "exchange": "BSE"},
        ]
        found, _ = build_instrument_map(instruments, ["RELIANCE"], exchange="NSE")
        assert found["RELIANCE"] == 1

    def test_all_symbols_found(self):
        found, missing = build_instrument_map(_FAKE_INSTRUMENTS, ["RELIANCE", "TCS", "INFY"])
        assert len(found) == 3
        assert missing == []


# ---------------------------------------------------------------------------
# Tests: dry run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_does_not_call_broker(self):
        broker = _FakeBroker()
        config = _make_config(dry_run=True)
        run_download(config, broker=broker)
        assert broker.get_instruments_calls == 0
        assert broker.get_historical_data_calls == []

    def test_dry_run_result_has_correct_symbols_requested(self):
        config = _make_config(dry_run=True)
        result = run_download(config, broker=None)
        assert set(result.symbols_requested) == {"RELIANCE", "TCS"}

    def test_dry_run_result_flags(self):
        config = _make_config(dry_run=True)
        result = run_download(config, broker=None)
        assert result.dry_run is True
        assert result.symbols_downloaded == []
        assert result.symbols_failed == []

    def test_dry_run_with_symbol_override(self):
        config = _make_config(symbols=["RELIANCE"], dry_run=True)
        result = run_download(config, broker=None)
        assert result.symbols_requested == ["RELIANCE"]


# ---------------------------------------------------------------------------
# Tests: real download (fake broker)
# ---------------------------------------------------------------------------


class TestRunDownload:
    def test_downloads_all_universe_symbols(self):
        broker = _FakeBroker()
        config = _make_config()
        result = run_download(config, broker=broker)
        assert set(result.symbols_downloaded) == {"RELIANCE", "TCS"}
        assert result.symbols_failed == []
        assert result.symbols_missing_token == []

    def test_calls_get_historical_data_per_symbol(self):
        broker = _FakeBroker()
        config = _make_config()
        run_download(config, broker=broker)
        assert len(broker.get_historical_data_calls) == 2

    def test_symbol_override_restricts_download(self):
        broker = _FakeBroker()
        config = _make_config(symbols=["RELIANCE"])
        result = run_download(config, broker=broker)
        assert result.symbols_downloaded == ["RELIANCE"]
        assert len(broker.get_historical_data_calls) == 1

    def test_missing_token_symbol_skipped(self):
        broker = _FakeBroker()
        config = _make_config(universe=_make_universe(["RELIANCE", "NOTLISTED"]), symbols=[])
        result = run_download(config, broker=broker)
        assert "RELIANCE" in result.symbols_downloaded
        assert "NOTLISTED" in result.symbols_missing_token

    def test_broker_error_recorded_in_failed(self):
        class _ErrorBroker(_FakeBroker):
            def get_historical_data(self, **kwargs: object) -> list:
                raise RuntimeError("API error")

        broker = _ErrorBroker()
        config = _make_config(symbols=["RELIANCE"])
        result = run_download(config, broker=broker)
        assert "RELIANCE" in result.symbols_failed
        assert result.symbols_downloaded == []

    def test_validation_reports_present(self):
        broker = _FakeBroker()
        config = _make_config(symbols=["RELIANCE"])
        result = run_download(config, broker=broker)
        assert "RELIANCE" in result.validation_reports

    def test_result_is_not_dry_run(self):
        broker = _FakeBroker()
        config = _make_config()
        result = run_download(config, broker=broker)
        assert result.dry_run is False


# ---------------------------------------------------------------------------
# Tests: download config target_symbols
# ---------------------------------------------------------------------------


class TestDownloadConfig:
    def test_target_symbols_uses_universe_when_no_override(self):
        config = _make_config()
        assert set(config.target_symbols()) == {"RELIANCE", "TCS"}

    def test_target_symbols_uses_override_when_provided(self):
        config = _make_config(symbols=["INFY"])
        assert config.target_symbols() == ["INFY"]


# ---------------------------------------------------------------------------
# Tests: DownloadResult.print_summary (smoke test — no crash)
# ---------------------------------------------------------------------------


class TestDownloadResultPrintSummary:
    def test_print_summary_does_not_crash(self, capsys):
        result = DownloadResult(
            symbols_requested=["RELIANCE"],
            symbols_downloaded=["RELIANCE"],
            symbols_failed=[],
            symbols_missing_token=[],
            validation_reports={},
            file_paths={},
            dry_run=False,
        )
        result.print_summary()
        captured = capsys.readouterr()
        assert "RELIANCE" in captured.out

    def test_print_summary_dry_run_tagged(self, capsys):
        result = DownloadResult(
            symbols_requested=["RELIANCE"],
            symbols_downloaded=[],
            symbols_failed=[],
            symbols_missing_token=[],
            validation_reports={},
            file_paths={},
            dry_run=True,
        )
        result.print_summary()
        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out
