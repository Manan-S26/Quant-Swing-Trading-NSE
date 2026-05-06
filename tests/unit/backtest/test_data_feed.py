"""Tests for HistoricalDataFeed."""

from __future__ import annotations

import pandas as pd
import pytest

from trading_engine.backtest.data_feed import HistoricalDataFeed
from trading_engine.strategy.signals import Bar


def _make_df(timestamps: list[str], base_price: float = 100.0) -> pd.DataFrame:
    rows = []
    for ts in timestamps:
        rows.append(
            {
                "timestamp": pd.Timestamp(ts),
                "open": base_price,
                "high": base_price + 2,
                "low": base_price - 2,
                "close": base_price + 1,
                "volume": 1000,
            }
        )
    return pd.DataFrame(rows)


class TestHistoricalDataFeedSingleSymbol:
    def test_yields_correct_number_of_bars(self) -> None:
        df = _make_df(["2024-01-15 09:15:00", "2024-01-15 09:16:00", "2024-01-15 09:17:00"])
        feed = HistoricalDataFeed({"RELIANCE": df})
        bars = list(feed.iter_bars())
        assert len(bars) == 3

    def test_yields_bar_objects(self) -> None:
        df = _make_df(["2024-01-15 09:15:00"])
        feed = HistoricalDataFeed({"RELIANCE": df})
        ts, sym, bar = next(iter(feed.iter_bars()))
        assert isinstance(bar, Bar)

    def test_symbol_in_bar(self) -> None:
        df = _make_df(["2024-01-15 09:15:00"])
        feed = HistoricalDataFeed({"RELIANCE": df})
        _, sym, bar = next(iter(feed.iter_bars()))
        assert sym == "RELIANCE"
        assert bar.symbol == "RELIANCE"

    def test_bars_sorted_ascending(self) -> None:
        # Provide out-of-order rows; feed must sort.
        df = _make_df(
            [
                "2024-01-15 09:17:00",
                "2024-01-15 09:15:00",
                "2024-01-15 09:16:00",
            ]
        )
        feed = HistoricalDataFeed({"RELIANCE": df})
        timestamps = [ts for ts, _, _ in feed.iter_bars()]
        assert timestamps == sorted(timestamps)

    def test_timestamp_in_tuple_matches_bar(self) -> None:
        df = _make_df(["2024-01-15 09:15:00"])
        feed = HistoricalDataFeed({"RELIANCE": df})
        ts, _, bar = next(iter(feed.iter_bars()))
        assert ts == bar.timestamp

    def test_bar_ohlcv_values(self) -> None:
        df = _make_df(["2024-01-15 09:15:00"], base_price=500.0)
        feed = HistoricalDataFeed({"RELIANCE": df})
        _, _, bar = next(iter(feed.iter_bars()))
        from decimal import Decimal

        assert bar.open == Decimal("500.0")
        assert bar.high == Decimal("502.0")
        assert bar.low == Decimal("498.0")
        assert bar.close == Decimal("501.0")
        assert bar.volume == 1000


class TestHistoricalDataFeedMultiSymbol:
    def test_multi_symbol_total_bar_count(self) -> None:
        df1 = _make_df(["2024-01-15 09:15:00", "2024-01-15 09:16:00"])
        df2 = _make_df(["2024-01-15 09:15:00", "2024-01-15 09:16:00"])
        feed = HistoricalDataFeed({"RELIANCE": df1, "INFY": df2})
        bars = list(feed.iter_bars())
        assert len(bars) == 4

    def test_multi_symbol_globally_sorted(self) -> None:
        df1 = _make_df(["2024-01-15 09:17:00", "2024-01-15 09:15:00"])
        df2 = _make_df(["2024-01-15 09:16:00"])
        feed = HistoricalDataFeed({"RELIANCE": df1, "INFY": df2})
        timestamps = [ts for ts, _, _ in feed.iter_bars()]
        assert timestamps == sorted(timestamps)

    def test_multi_symbol_all_symbols_present(self) -> None:
        df1 = _make_df(["2024-01-15 09:15:00"])
        df2 = _make_df(["2024-01-15 09:16:00"])
        feed = HistoricalDataFeed({"RELIANCE": df1, "INFY": df2})
        symbols = {sym for _, sym, _ in feed.iter_bars()}
        assert symbols == {"RELIANCE", "INFY"}


class TestHistoricalDataFeedValidation:
    def test_missing_timestamp_raises(self) -> None:
        df = _make_df(["2024-01-15 09:15:00"]).drop(columns=["timestamp"])
        with pytest.raises(ValueError, match="missing required columns"):
            HistoricalDataFeed({"RELIANCE": df})

    def test_missing_close_raises(self) -> None:
        df = _make_df(["2024-01-15 09:15:00"]).drop(columns=["close"])
        with pytest.raises(ValueError, match="missing required columns"):
            HistoricalDataFeed({"RELIANCE": df})

    def test_missing_volume_raises(self) -> None:
        df = _make_df(["2024-01-15 09:15:00"]).drop(columns=["volume"])
        with pytest.raises(ValueError, match="missing required columns"):
            HistoricalDataFeed({"RELIANCE": df})


class TestHistoricalDataFeedImmutability:
    def test_original_dataframe_not_mutated(self) -> None:
        df = _make_df(["2024-01-15 09:17:00", "2024-01-15 09:15:00"])
        original_first_ts = df.iloc[0]["timestamp"]
        feed = HistoricalDataFeed({"RELIANCE": df})
        list(feed.iter_bars())
        # Original should still have the same first row.
        assert df.iloc[0]["timestamp"] == original_first_ts
