"""Tests for OHLCV DataFrame validation."""

from __future__ import annotations

import pandas as pd

from trading_engine.data.validation import (
    DataValidationReport,
    validate_ohlcv_dataframe,
)
from trading_engine.domain.enums import Exchange

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candle(
    timestamp: str = "2024-01-15 09:15:00",
    open_: float = 2800.0,
    high: float = 2820.0,
    low: float = 2790.0,
    close: float = 2810.0,
    volume: int = 10000,
) -> dict:
    return {
        "timestamp": pd.Timestamp(timestamp),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _make_df(rows: list[dict] | None = None) -> pd.DataFrame:
    if rows is None:
        rows = [
            _make_candle("2024-01-15 09:15:00"),
            _make_candle("2024-01-15 09:16:00"),
            _make_candle("2024-01-15 09:17:00"),
        ]
    return pd.DataFrame(rows)


def _validate(df: pd.DataFrame, interval: str = "minute") -> DataValidationReport:
    return validate_ohlcv_dataframe(df, "RELIANCE", Exchange.NSE, interval)


def _error_codes(report: DataValidationReport) -> set[str]:
    return {i.code for i in report.issues if i.severity == "error"}


def _warning_codes(report: DataValidationReport) -> set[str]:
    return {i.code for i in report.issues if i.severity == "warning"}


# ---------------------------------------------------------------------------
# Valid data
# ---------------------------------------------------------------------------


class TestValidData:
    def test_valid_dataframe_is_valid(self) -> None:
        report = _validate(_make_df())
        assert report.is_valid is True
        assert _error_codes(report) == set()

    def test_valid_report_has_correct_row_count(self) -> None:
        df = _make_df()
        report = _validate(df)
        assert report.row_count == 3

    def test_valid_report_has_start_end_timestamps(self) -> None:
        report = _validate(_make_df())
        assert report.start_timestamp is not None
        assert report.end_timestamp is not None
        assert report.end_timestamp > report.start_timestamp

    def test_valid_report_exchange_and_interval(self) -> None:
        report = _validate(_make_df())
        assert report.exchange == Exchange.NSE
        assert report.interval == "minute"

    def test_single_row_is_valid(self) -> None:
        df = _make_df([_make_candle()])
        report = _validate(df)
        assert report.is_valid is True


# ---------------------------------------------------------------------------
# Missing required columns
# ---------------------------------------------------------------------------


class TestMissingColumns:
    def test_missing_timestamp_is_invalid(self) -> None:
        df = _make_df().drop(columns=["timestamp"])
        report = _validate(df)
        assert report.is_valid is False
        assert "MISSING_COLUMN" in _error_codes(report)

    def test_missing_open_is_invalid(self) -> None:
        df = _make_df().drop(columns=["open"])
        report = _validate(df)
        assert "MISSING_COLUMN" in _error_codes(report)

    def test_missing_high_is_invalid(self) -> None:
        df = _make_df().drop(columns=["high"])
        report = _validate(df)
        assert "MISSING_COLUMN" in _error_codes(report)

    def test_missing_low_is_invalid(self) -> None:
        df = _make_df().drop(columns=["low"])
        report = _validate(df)
        assert "MISSING_COLUMN" in _error_codes(report)

    def test_missing_close_is_invalid(self) -> None:
        df = _make_df().drop(columns=["close"])
        report = _validate(df)
        assert "MISSING_COLUMN" in _error_codes(report)

    def test_missing_volume_is_invalid(self) -> None:
        df = _make_df().drop(columns=["volume"])
        report = _validate(df)
        assert "MISSING_COLUMN" in _error_codes(report)


# ---------------------------------------------------------------------------
# Empty DataFrame
# ---------------------------------------------------------------------------


class TestEmptyDataFrame:
    def test_empty_dataframe_is_invalid(self) -> None:
        df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        report = _validate(df)
        assert report.is_valid is False
        assert "EMPTY_DATAFRAME" in _error_codes(report)

    def test_empty_dataframe_row_count_is_zero(self) -> None:
        df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        report = _validate(df)
        assert report.row_count == 0


# ---------------------------------------------------------------------------
# Duplicate timestamps
# ---------------------------------------------------------------------------


class TestDuplicateTimestamps:
    def test_duplicate_timestamps_is_invalid(self) -> None:
        rows = [
            _make_candle("2024-01-15 09:15:00"),
            _make_candle("2024-01-15 09:15:00"),  # duplicate
            _make_candle("2024-01-15 09:17:00"),
        ]
        report = _validate(_make_df(rows))
        assert report.is_valid is False
        assert "DUPLICATE_TIMESTAMP" in _error_codes(report)


# ---------------------------------------------------------------------------
# Price validation
# ---------------------------------------------------------------------------


class TestPriceValidation:
    def test_zero_open_is_invalid(self) -> None:
        rows = [_make_candle(open_=0.0, high=10.0, low=0.0)]
        report = _validate(_make_df(rows))
        assert "NON_POSITIVE_PRICE" in _error_codes(report)

    def test_negative_close_is_invalid(self) -> None:
        rows = [_make_candle(close=-100.0)]
        report = _validate(_make_df(rows))
        assert "NON_POSITIVE_PRICE" in _error_codes(report)

    def test_zero_high_is_invalid(self) -> None:
        rows = [_make_candle(high=0.0, open_=0.0, low=0.0, close=0.0)]
        report = _validate(_make_df(rows))
        assert "NON_POSITIVE_PRICE" in _error_codes(report)

    def test_zero_low_is_invalid(self) -> None:
        rows = [_make_candle(low=0.0)]
        report = _validate(_make_df(rows))
        assert "NON_POSITIVE_PRICE" in _error_codes(report)


# ---------------------------------------------------------------------------
# Volume validation
# ---------------------------------------------------------------------------


class TestVolumeValidation:
    def test_negative_volume_is_invalid(self) -> None:
        rows = [_make_candle(volume=-1)]
        report = _validate(_make_df(rows))
        assert report.is_valid is False
        assert "NEGATIVE_VOLUME" in _error_codes(report)

    def test_zero_volume_is_valid(self) -> None:
        rows = [_make_candle(volume=0)]
        report = _validate(_make_df(rows))
        # Zero volume is technically valid (halted stock, holiday, etc.)
        assert "NEGATIVE_VOLUME" not in _error_codes(report)


# ---------------------------------------------------------------------------
# OHLC relationship checks
# ---------------------------------------------------------------------------


class TestOHLCRelationships:
    def test_high_below_close_is_invalid(self) -> None:
        # high=2790, close=2810 → high < close
        rows = [_make_candle(open_=2800, high=2790, low=2780, close=2810)]
        report = _validate(_make_df(rows))
        assert report.is_valid is False
        assert "INVALID_HIGH" in _error_codes(report)

    def test_high_below_open_is_invalid(self) -> None:
        rows = [_make_candle(open_=2850, high=2800, low=2780, close=2810)]
        report = _validate(_make_df(rows))
        assert "INVALID_HIGH" in _error_codes(report)

    def test_low_above_close_is_invalid(self) -> None:
        rows = [_make_candle(open_=2800, high=2820, low=2830, close=2810)]
        report = _validate(_make_df(rows))
        assert report.is_valid is False
        assert "INVALID_LOW" in _error_codes(report)

    def test_low_above_open_is_invalid(self) -> None:
        rows = [_make_candle(open_=2780, high=2820, low=2800, close=2810)]
        report = _validate(_make_df(rows))
        assert "INVALID_LOW" in _error_codes(report)

    def test_valid_ohlc_relationships_pass(self) -> None:
        # open=close=high=low (flat candle) → valid
        rows = [_make_candle(open_=2800, high=2800, low=2800, close=2800)]
        report = _validate(_make_df(rows))
        assert "INVALID_HIGH" not in _error_codes(report)
        assert "INVALID_LOW" not in _error_codes(report)


# ---------------------------------------------------------------------------
# Sort order
# ---------------------------------------------------------------------------


class TestSortOrder:
    def test_unsorted_timestamps_is_invalid(self) -> None:
        rows = [
            _make_candle("2024-01-15 09:17:00"),
            _make_candle("2024-01-15 09:15:00"),  # out of order
            _make_candle("2024-01-15 09:16:00"),
        ]
        report = _validate(_make_df(rows))
        assert report.is_valid is False
        assert "UNSORTED_TIMESTAMPS" in _error_codes(report)

    def test_sorted_timestamps_pass(self) -> None:
        report = _validate(_make_df())  # fixture is sorted
        assert "UNSORTED_TIMESTAMPS" not in _error_codes(report)


# ---------------------------------------------------------------------------
# Gap detection (warnings)
# ---------------------------------------------------------------------------


class TestGapDetection:
    def test_large_gap_produces_warning(self) -> None:
        rows = [
            _make_candle("2024-01-15 09:15:00"),
            _make_candle("2024-01-15 09:16:00"),
            # 3-hour gap >> 10 * 1 minute threshold
            _make_candle("2024-01-15 12:16:00"),
            _make_candle("2024-01-15 12:17:00"),
        ]
        report = _validate(_make_df(rows), interval="minute")
        assert "POSSIBLE_MISSING_CANDLES" in _warning_codes(report)
        # Still valid — gap is a warning not an error
        assert report.is_valid is True

    def test_normal_gaps_no_warning(self) -> None:
        report = _validate(_make_df(), interval="minute")
        assert "POSSIBLE_MISSING_CANDLES" not in _warning_codes(report)

    def test_day_interval_no_gap_detection(self) -> None:
        # "day" interval is not in _INTERVAL_MINUTES so no gap check runs
        rows = [
            _make_candle("2024-01-15 00:00:00"),
            _make_candle("2024-01-22 00:00:00"),  # 1 week gap — normal for day candles
        ]
        report = _validate(_make_df(rows), interval="day")
        assert "POSSIBLE_MISSING_CANDLES" not in _warning_codes(report)
