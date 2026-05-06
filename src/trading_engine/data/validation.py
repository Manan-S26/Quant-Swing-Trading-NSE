"""OHLCV DataFrame validation for historical candle data.

Validates that a candle DataFrame is structurally correct and internally
consistent before it is saved or used by a strategy.

Usage:
    report = validate_ohlcv_dataframe(df, "RELIANCE", Exchange.NSE, "minute")
    if not report.is_valid:
        for issue in report.issues:
            print(issue.severity, issue.code, issue.message)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from trading_engine.domain.enums import Exchange

# Required columns in every OHLCV DataFrame.
_REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")

# Expected interval in minutes; used for simple gap detection.
_INTERVAL_MINUTES: dict[str, int] = {
    "minute": 1,
    "1minute": 1,
    "3minute": 3,
    "5minute": 5,
    "15minute": 15,
    "30minute": 30,
    "60minute": 60,
}

# Gap-detection threshold: warn if a gap is this many times larger than expected.
_GAP_THRESHOLD_MULTIPLIER = 10


@dataclass
class DataValidationIssue:
    """A single validation finding (error or warning)."""

    severity: str  # "error" | "warning"
    code: str
    message: str
    symbol: str | None = None
    timestamp: datetime | None = None
    row_index: int | None = None


@dataclass
class DataValidationReport:
    """Aggregated validation result for a single symbol/interval."""

    symbol: str
    exchange: Exchange
    interval: str
    row_count: int
    start_timestamp: datetime | None
    end_timestamp: datetime | None
    is_valid: bool
    issues: list[DataValidationIssue] = field(default_factory=list)


def validate_ohlcv_dataframe(
    df: pd.DataFrame,
    symbol: str,
    exchange: Exchange,
    interval: str,
) -> DataValidationReport:
    """Validate an OHLCV candle DataFrame.

    Returns a DataValidationReport. ``is_valid`` is True only when there are
    no "error"-severity issues. Warnings are informational.

    Checks performed:
      - Required columns present
      - DataFrame not empty
      - No duplicate timestamps
      - OHLC values are positive (> 0)
      - Volume is non-negative (>= 0)
      - high >= open, close, low for every row
      - low <= open, close, high for every row
      - DataFrame sorted by timestamp (ascending)
      - Obvious timestamp gaps for supported intraday intervals (warning only)
    """
    issues: list[DataValidationIssue] = []

    # -----------------------------------------------------------------------
    # 1. Required columns
    # -----------------------------------------------------------------------
    missing_cols = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    for col in missing_cols:
        issues.append(
            DataValidationIssue(
                severity="error",
                code="MISSING_COLUMN",
                message=f"Required column '{col}' is missing.",
                symbol=symbol,
            )
        )

    # If columns are missing we can't safely run remaining checks.
    if missing_cols:
        return DataValidationReport(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            row_count=len(df),
            start_timestamp=None,
            end_timestamp=None,
            is_valid=False,
            issues=issues,
        )

    # -----------------------------------------------------------------------
    # 2. Empty DataFrame
    # -----------------------------------------------------------------------
    if df.empty:
        issues.append(
            DataValidationIssue(
                severity="error",
                code="EMPTY_DATAFRAME",
                message="DataFrame contains no rows.",
                symbol=symbol,
            )
        )
        return DataValidationReport(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            row_count=0,
            start_timestamp=None,
            end_timestamp=None,
            is_valid=False,
            issues=issues,
        )

    # Coerce timestamps for subsequent checks.
    try:
        ts = pd.to_datetime(df["timestamp"])
    except Exception as exc:
        issues.append(
            DataValidationIssue(
                severity="error",
                code="INVALID_TIMESTAMP",
                message=f"timestamp column cannot be parsed as datetime: {exc}",
                symbol=symbol,
            )
        )
        ts = pd.Series(dtype="datetime64[ns]")

    start_ts: datetime | None = ts.min().to_pydatetime() if not ts.empty else None
    end_ts: datetime | None = ts.max().to_pydatetime() if not ts.empty else None

    # -----------------------------------------------------------------------
    # 3. Duplicate timestamps
    # -----------------------------------------------------------------------
    if not ts.empty:
        dupes = ts[ts.duplicated()]
        if not dupes.empty:
            for dup_ts in dupes.unique():
                issues.append(
                    DataValidationIssue(
                        severity="error",
                        code="DUPLICATE_TIMESTAMP",
                        message=f"Duplicate timestamp found: {dup_ts}",
                        symbol=symbol,
                        timestamp=dup_ts.to_pydatetime(),
                    )
                )

    # -----------------------------------------------------------------------
    # 4. Positive OHLC
    # -----------------------------------------------------------------------
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            bad = df[pd.to_numeric(df[col], errors="coerce") <= 0]
            for idx in bad.index:
                issues.append(
                    DataValidationIssue(
                        severity="error",
                        code="NON_POSITIVE_PRICE",
                        message=f"Column '{col}' has non-positive value {df.at[idx, col]!r} at row {idx}.",
                        symbol=symbol,
                        row_index=int(idx),
                    )
                )

    # -----------------------------------------------------------------------
    # 5. Non-negative volume
    # -----------------------------------------------------------------------
    if "volume" in df.columns:
        bad_vol = df[pd.to_numeric(df["volume"], errors="coerce") < 0]
        for idx in bad_vol.index:
            issues.append(
                DataValidationIssue(
                    severity="error",
                    code="NEGATIVE_VOLUME",
                    message=f"volume is negative ({df.at[idx, 'volume']!r}) at row {idx}.",
                    symbol=symbol,
                    row_index=int(idx),
                )
            )

    # -----------------------------------------------------------------------
    # 6. OHLC relationship — high must be the maximum, low the minimum
    # -----------------------------------------------------------------------
    ohlc_cols = {"open", "high", "low", "close"}
    if ohlc_cols.issubset(df.columns):
        num = df[list(ohlc_cols)].apply(pd.to_numeric, errors="coerce")

        # high < open or high < close or high < low
        bad_high = num[
            (num["high"] < num["open"]) | (num["high"] < num["close"]) | (num["high"] < num["low"])
        ]
        for idx in bad_high.index:
            issues.append(
                DataValidationIssue(
                    severity="error",
                    code="INVALID_HIGH",
                    message=(
                        f"high ({num.at[idx, 'high']}) is less than open/close/low at row {idx}."
                    ),
                    symbol=symbol,
                    row_index=int(idx),
                )
            )

        # low > open or low > close or low > high
        bad_low = num[
            (num["low"] > num["open"]) | (num["low"] > num["close"]) | (num["low"] > num["high"])
        ]
        for idx in bad_low.index:
            issues.append(
                DataValidationIssue(
                    severity="error",
                    code="INVALID_LOW",
                    message=(
                        f"low ({num.at[idx, 'low']}) is greater than open/close/high at row {idx}."
                    ),
                    symbol=symbol,
                    row_index=int(idx),
                )
            )

    # -----------------------------------------------------------------------
    # 7. Sort order
    # -----------------------------------------------------------------------
    if not ts.empty and not ts.is_monotonic_increasing:
        issues.append(
            DataValidationIssue(
                severity="error",
                code="UNSORTED_TIMESTAMPS",
                message="Timestamps are not sorted in ascending order.",
                symbol=symbol,
            )
        )

    # -----------------------------------------------------------------------
    # 8. Gap detection (warning only, intraday intervals only)
    # -----------------------------------------------------------------------
    if interval in _INTERVAL_MINUTES and not ts.empty and len(ts) > 1:
        sorted_ts = ts.sort_values().reset_index(drop=True)
        diffs = sorted_ts.diff().dropna()
        expected = pd.Timedelta(minutes=_INTERVAL_MINUTES[interval])
        threshold = expected * _GAP_THRESHOLD_MULTIPLIER
        large_gaps = diffs[diffs > threshold]
        for idx in large_gaps.index:
            gap_start = sorted_ts.iloc[idx - 1]
            gap_end = sorted_ts.iloc[idx]
            issues.append(
                DataValidationIssue(
                    severity="warning",
                    code="POSSIBLE_MISSING_CANDLES",
                    message=(
                        f"Large gap detected: {gap_start} → {gap_end} "
                        f"({diffs.iloc[idx]}). Expected ~{expected}."
                    ),
                    symbol=symbol,
                    timestamp=gap_end.to_pydatetime(),
                )
            )

    # -----------------------------------------------------------------------
    # Result
    # -----------------------------------------------------------------------
    has_errors = any(i.severity == "error" for i in issues)
    return DataValidationReport(
        symbol=symbol,
        exchange=exchange,
        interval=interval,
        row_count=len(df),
        start_timestamp=start_ts,
        end_timestamp=end_ts,
        is_valid=not has_errors,
        issues=issues,
    )
