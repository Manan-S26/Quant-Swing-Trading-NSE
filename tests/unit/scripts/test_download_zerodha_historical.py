"""Tests for Zerodha historical data download logic.

All tests use fake brokers and fake data — no real Zerodha API calls.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from trading_engine.data.universe import UniverseConfig
from trading_engine.data.zerodha_downloader import (
    INTRADAY_INTERVALS,
    DownloadConfig,
    DownloadResult,
    assert_live_trading_disabled,
    build_instrument_map,
    run_download,
    split_date_range,
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


# ---------------------------------------------------------------------------
# Tests: split_date_range
# ---------------------------------------------------------------------------


class TestSplitDateRange:
    def test_single_chunk_when_range_fits(self):
        chunks = split_date_range(datetime(2024, 1, 1), datetime(2024, 1, 30), chunk_days=60)
        assert len(chunks) == 1
        assert chunks[0] == (datetime(2024, 1, 1), datetime(2024, 1, 30))

    def test_exactly_one_chunk_at_boundary(self):
        # Jan 1 + 59 days = Feb 29 (2024 is a leap year), so Jan 1 → Feb 29 is exactly 60 days
        chunks = split_date_range(datetime(2024, 1, 1), datetime(2024, 2, 29), chunk_days=60)
        assert len(chunks) == 1

    def test_two_chunks_when_range_exceeds_limit(self):
        # Jan 1 → Mar 31 is ~90 days with chunk_days=60 → 2 chunks
        chunks = split_date_range(datetime(2024, 1, 1), datetime(2024, 3, 31), chunk_days=60)
        assert len(chunks) == 2

    def test_chunks_are_contiguous_with_no_gaps(self):
        chunks = split_date_range(datetime(2024, 1, 1), datetime(2024, 6, 30), chunk_days=60)
        for i in range(len(chunks) - 1):
            _, end_prev = chunks[i]
            start_next, _ = chunks[i + 1]
            assert start_next == end_prev + timedelta(days=1)

    def test_chunks_cover_full_range(self):
        from_date = datetime(2024, 1, 1)
        to_date = datetime(2024, 12, 31)
        chunks = split_date_range(from_date, to_date, chunk_days=60)
        assert chunks[0][0] == from_date
        assert chunks[-1][1] == to_date

    def test_chunk_size_does_not_exceed_limit(self):
        chunks = split_date_range(datetime(2024, 1, 1), datetime(2024, 12, 31), chunk_days=60)
        for c_from, c_to in chunks:
            days = (c_to - c_from).days + 1
            assert days <= 60

    def test_single_day_range_is_one_chunk(self):
        chunks = split_date_range(datetime(2024, 1, 15), datetime(2024, 1, 15), chunk_days=60)
        assert len(chunks) == 1
        assert chunks[0] == (datetime(2024, 1, 15), datetime(2024, 1, 15))

    def test_invalid_chunk_days_raises(self):
        with pytest.raises(ValueError):
            split_date_range(datetime(2024, 1, 1), datetime(2024, 1, 31), chunk_days=0)

    def test_chunk_days_one_produces_daily_chunks(self):
        chunks = split_date_range(datetime(2024, 1, 1), datetime(2024, 1, 5), chunk_days=1)
        assert len(chunks) == 5
        for c_from, c_to in chunks:
            assert c_from == c_to  # each chunk is a single day


# ---------------------------------------------------------------------------
# Tests: intraday_intervals constant
# ---------------------------------------------------------------------------


class TestIntradayIntervals:
    def test_minute_is_intraday(self):
        assert "minute" in INTRADAY_INTERVALS

    def test_day_is_not_intraday(self):
        assert "day" not in INTRADAY_INTERVALS

    def test_known_intraday_intervals_present(self):
        for interval in ("3minute", "5minute", "10minute", "15minute", "30minute", "60minute"):
            assert interval in INTRADAY_INTERVALS


# ---------------------------------------------------------------------------
# Tests: chunked download with merge (fake broker + tmp_path)
# ---------------------------------------------------------------------------


def _make_candle(ts: datetime, close: float = 100.0) -> dict:
    return {
        "date": ts,
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 1000,
    }


class _ChunkedFakeBroker:
    """Broker that returns different candles per date range to simulate chunks."""

    def __init__(self, candle_map: dict[tuple[datetime, datetime], list[dict]]) -> None:
        self._map = candle_map
        self.get_historical_data_calls: list[dict] = []
        self.get_instruments_calls: int = 0

    def get_instruments(self, exchange: str) -> list[dict]:
        self.get_instruments_calls += 1
        return _FAKE_INSTRUMENTS

    def get_historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
    ) -> list[dict]:
        self.get_historical_data_calls.append(
            {"from": from_date, "to": to_date, "interval": interval}
        )
        # Return candles for the matching chunk, or empty list.
        for (c_from, c_to), candles in self._map.items():
            if c_from == from_date and c_to == to_date:
                return candles
        return []


def _chunked_config(
    tmp_path: Path,
    chunk_days: int = 60,
    replace: bool = False,
    symbols: list[str] | None = None,
    dry_run: bool = False,
    interval: str = "minute",
) -> DownloadConfig:
    return DownloadConfig(
        universe=UniverseConfig(name="test", exchange="NSE", symbols=["RELIANCE"]),
        interval=interval,
        from_date=datetime(2024, 1, 1),
        to_date=datetime(2024, 3, 31),
        data_dir=str(tmp_path),
        symbols=symbols or [],
        dry_run=dry_run,
        save=True,
        chunk_days=chunk_days,
        replace=replace,
    )


class TestChunkedDownload:
    def test_date_range_split_into_two_chunks(self, tmp_path: Path):
        """90-day range with chunk_days=60 → 2 broker calls per symbol."""
        chunk1_from = datetime(2024, 1, 1)
        chunk1_to = datetime(2024, 2, 29)  # 60 days
        chunk2_from = datetime(2024, 3, 1)
        chunk2_to = datetime(2024, 3, 31)

        candle_map = {
            (chunk1_from, chunk1_to): [_make_candle(datetime(2024, 1, 15, 9, 15))],
            (chunk2_from, chunk2_to): [_make_candle(datetime(2024, 3, 15, 9, 15))],
        }
        broker = _ChunkedFakeBroker(candle_map)
        config = _chunked_config(tmp_path, chunk_days=60)
        result = run_download(config, broker=broker)

        assert "RELIANCE" in result.symbols_downloaded
        assert len(broker.get_historical_data_calls) == 2

    def test_existing_parquet_is_merged(self, tmp_path: Path):
        """New download is merged with data already on disk."""
        # Write a pre-existing Parquet with one candle.
        existing_ts = datetime(2023, 12, 1, 9, 15)
        existing_df = pd.DataFrame(
            [
                {
                    "timestamp": existing_ts,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 500,
                }
            ]
        )
        parquet_path = tmp_path / "candles" / "NSE" / "RELIANCE" / "minute.parquet"
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        existing_df.to_parquet(parquet_path, index=False)

        # Broker returns a new candle.
        new_ts = datetime(2024, 1, 15, 9, 15)
        chunk1_from = datetime(2024, 1, 1)
        chunk1_to = datetime(2024, 2, 29)
        chunk2_from = datetime(2024, 3, 1)
        chunk2_to = datetime(2024, 3, 31)
        candle_map = {
            (chunk1_from, chunk1_to): [_make_candle(new_ts)],
            (chunk2_from, chunk2_to): [],
        }
        broker = _ChunkedFakeBroker(candle_map)
        config = _chunked_config(tmp_path, replace=False)
        run_download(config, broker=broker)

        merged = pd.read_parquet(parquet_path)
        timestamps = pd.to_datetime(merged["timestamp"]).tolist()
        existing_ts_pd = pd.Timestamp(existing_ts)
        new_ts_pd = pd.Timestamp(new_ts)
        assert existing_ts_pd in timestamps
        assert new_ts_pd in timestamps
        assert len(merged) == 2

    def test_duplicate_timestamps_are_removed(self, tmp_path: Path):
        """If new download overlaps with existing data, duplicates are dropped."""
        shared_ts = datetime(2024, 1, 15, 9, 15)

        # Existing Parquet already has the same candle.
        existing_df = pd.DataFrame(
            [
                {
                    "timestamp": shared_ts,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 500,
                }
            ]
        )
        parquet_path = tmp_path / "candles" / "NSE" / "RELIANCE" / "minute.parquet"
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        existing_df.to_parquet(parquet_path, index=False)

        chunk1_from = datetime(2024, 1, 1)
        chunk1_to = datetime(2024, 2, 29)
        chunk2_from = datetime(2024, 3, 1)
        chunk2_to = datetime(2024, 3, 31)
        candle_map = {
            (chunk1_from, chunk1_to): [_make_candle(shared_ts)],  # same timestamp
            (chunk2_from, chunk2_to): [],
        }
        broker = _ChunkedFakeBroker(candle_map)
        config = _chunked_config(tmp_path, replace=False)
        run_download(config, broker=broker)

        merged = pd.read_parquet(parquet_path)
        assert len(merged) == 1  # duplicate removed

    def test_final_data_is_sorted_by_timestamp(self, tmp_path: Path):
        """Merged result must be sorted ascending by timestamp."""
        # Existing Parquet has a later candle.
        later_ts = datetime(2024, 3, 20, 9, 15)
        existing_df = pd.DataFrame(
            [
                {
                    "timestamp": later_ts,
                    "open": 200.0,
                    "high": 201.0,
                    "low": 199.0,
                    "close": 200.5,
                    "volume": 200,
                }
            ]
        )
        parquet_path = tmp_path / "candles" / "NSE" / "RELIANCE" / "minute.parquet"
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        existing_df.to_parquet(parquet_path, index=False)

        # Broker returns an earlier candle.
        earlier_ts = datetime(2024, 1, 5, 9, 15)
        chunk1_from = datetime(2024, 1, 1)
        chunk1_to = datetime(2024, 2, 29)
        chunk2_from = datetime(2024, 3, 1)
        chunk2_to = datetime(2024, 3, 31)
        candle_map = {
            (chunk1_from, chunk1_to): [_make_candle(earlier_ts)],
            (chunk2_from, chunk2_to): [],
        }
        broker = _ChunkedFakeBroker(candle_map)
        config = _chunked_config(tmp_path, replace=False)
        run_download(config, broker=broker)

        merged = pd.read_parquet(parquet_path)
        timestamps = merged["timestamp"].tolist()
        assert timestamps == sorted(timestamps)

    def test_replace_overwrites_existing(self, tmp_path: Path):
        """--replace must discard existing Parquet and save only new data."""
        old_ts = datetime(2023, 6, 1, 9, 15)
        existing_df = pd.DataFrame(
            [
                {
                    "timestamp": old_ts,
                    "open": 50.0,
                    "high": 51.0,
                    "low": 49.0,
                    "close": 50.5,
                    "volume": 100,
                }
            ]
        )
        parquet_path = tmp_path / "candles" / "NSE" / "RELIANCE" / "minute.parquet"
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        existing_df.to_parquet(parquet_path, index=False)

        new_ts = datetime(2024, 1, 15, 9, 15)
        chunk1_from = datetime(2024, 1, 1)
        chunk1_to = datetime(2024, 2, 29)
        chunk2_from = datetime(2024, 3, 1)
        chunk2_to = datetime(2024, 3, 31)
        candle_map = {
            (chunk1_from, chunk1_to): [_make_candle(new_ts)],
            (chunk2_from, chunk2_to): [],
        }
        broker = _ChunkedFakeBroker(candle_map)
        config = _chunked_config(tmp_path, replace=True)
        run_download(config, broker=broker)

        saved = pd.read_parquet(parquet_path)
        saved_timestamps = saved["timestamp"].tolist()
        # Old data must be gone.
        assert not any(old_ts == t for t in saved_timestamps)
        # New data must be present.
        assert any(new_ts == t for t in saved_timestamps)

    def test_dry_run_does_not_call_api(self):
        """Dry-run with intraday interval must not call broker."""
        broker = _FakeBroker()
        config = DownloadConfig(
            universe=UniverseConfig(name="test", exchange="NSE", symbols=["RELIANCE"]),
            interval="minute",
            from_date=datetime(2024, 1, 1),
            to_date=datetime(2024, 3, 31),
            data_dir="./data",
            dry_run=True,
            chunk_days=60,
        )
        run_download(config, broker=broker)
        assert broker.get_instruments_calls == 0
        assert broker.get_historical_data_calls == []

    def test_dry_run_result_includes_chunks(self):
        """Dry-run result must report the planned chunks."""
        config = DownloadConfig(
            universe=UniverseConfig(name="test", exchange="NSE", symbols=["RELIANCE"]),
            interval="minute",
            from_date=datetime(2024, 1, 1),
            to_date=datetime(2024, 3, 31),
            data_dir="./data",
            dry_run=True,
            chunk_days=60,
        )
        result = run_download(config, broker=None)
        assert result.dry_run is True
        assert len(result.chunks) >= 2  # 90-day range → at least 2 chunks

    def test_non_intraday_interval_uses_single_chunk(self, tmp_path: Path):
        """Daily interval must use a single chunk regardless of date range."""
        candle_map = {
            (datetime(2024, 1, 1), datetime(2024, 3, 31)): [_make_candle(datetime(2024, 1, 15))],
        }
        broker = _ChunkedFakeBroker(candle_map)
        config = _chunked_config(tmp_path, chunk_days=60, interval="day")
        run_download(config, broker=broker)
        assert len(broker.get_historical_data_calls) == 1

    def test_download_config_chunk_days_default(self):
        config = DownloadConfig(
            universe=UniverseConfig(name="test", exchange="NSE", symbols=["RELIANCE"]),
            interval="minute",
            from_date=datetime(2024, 1, 1),
            to_date=datetime(2024, 1, 31),
        )
        assert config.chunk_days == 60

    def test_download_config_replace_default(self):
        config = DownloadConfig(
            universe=UniverseConfig(name="test", exchange="NSE", symbols=["RELIANCE"]),
            interval="minute",
            from_date=datetime(2024, 1, 1),
            to_date=datetime(2024, 1, 31),
        )
        assert config.replace is False
