"""Tests for PaperMarketFeed."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pandas as pd
import pytest

from trading_engine.paper.market_feed import PaperMarketFeed
from trading_engine.strategy.signals import Bar


def _make_bar(symbol: str, ts: str, price: float = 100.0) -> Bar:
    return Bar(
        symbol=symbol,
        exchange="NSE",
        timestamp=datetime.fromisoformat(ts),
        open=Decimal(str(price)),
        high=Decimal(str(price + 5)),
        low=Decimal(str(price - 5)),
        close=Decimal(str(price)),
        volume=1000,
        interval="minute",
    )


def _make_df(timestamps: list[str], symbol: str = "RELIANCE", price: float = 100.0) -> pd.DataFrame:
    rows = [
        {
            "timestamp": pd.Timestamp(ts),
            "open": price,
            "high": price + 5,
            "low": price - 5,
            "close": price,
            "volume": 1000,
        }
        for ts in timestamps
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Single-symbol, list[Bar] input
# ---------------------------------------------------------------------------


class TestSingleSymbolBarList:
    def test_yields_all_bars(self):
        bars = [_make_bar("RELIANCE", "2024-01-15T09:30:00")]
        feed = PaperMarketFeed({"RELIANCE": bars})
        result = list(feed.iter_bars())
        assert len(result) == 1
        ts, sym, bar = result[0]
        assert sym == "RELIANCE"
        assert bar.symbol == "RELIANCE"

    def test_yields_in_timestamp_order(self):
        bars = [
            _make_bar("RELIANCE", "2024-01-15T09:32:00"),
            _make_bar("RELIANCE", "2024-01-15T09:30:00"),
            _make_bar("RELIANCE", "2024-01-15T09:31:00"),
        ]
        feed = PaperMarketFeed({"RELIANCE": bars})
        result = list(feed.iter_bars())
        timestamps = [r[0] for r in result]
        assert timestamps == sorted(timestamps)

    def test_does_not_mutate_input_list(self):
        bars = [_make_bar("RELIANCE", "2024-01-15T09:30:00")]
        original_len = len(bars)
        feed = PaperMarketFeed({"RELIANCE": bars})
        list(feed.iter_bars())
        assert len(bars) == original_len


# ---------------------------------------------------------------------------
# Single-symbol, DataFrame input
# ---------------------------------------------------------------------------


class TestSingleSymbolDataFrame:
    def test_builds_bars_from_dataframe(self):
        df = _make_df(["2024-01-15 09:30:00", "2024-01-15 09:31:00"])
        feed = PaperMarketFeed({"RELIANCE": df})
        result = list(feed.iter_bars())
        assert len(result) == 2
        assert all(sym == "RELIANCE" for _, sym, _ in result)

    def test_does_not_mutate_dataframe(self):
        df = _make_df(["2024-01-15 09:30:00"])
        original_shape = df.shape
        feed = PaperMarketFeed({"RELIANCE": df})
        list(feed.iter_bars())
        assert df.shape == original_shape

    def test_missing_column_raises(self):
        df = pd.DataFrame({"timestamp": [pd.Timestamp("2024-01-15")], "open": [100]})
        with pytest.raises(ValueError, match="missing required columns"):
            PaperMarketFeed({"RELIANCE": df})

    def test_decimal_prices_built_correctly(self):
        df = _make_df(["2024-01-15 09:30:00"], price=523.75)
        feed = PaperMarketFeed({"RELIANCE": df})
        _, _, bar = list(feed.iter_bars())[0]
        assert bar.close == Decimal("523.75")


# ---------------------------------------------------------------------------
# Multi-symbol, globally sorted
# ---------------------------------------------------------------------------


class TestMultiSymbol:
    def test_globally_timestamp_sorted(self):
        bars = {
            "TCS": [
                _make_bar("TCS", "2024-01-15T09:31:00"),
                _make_bar("TCS", "2024-01-15T09:30:00"),
            ],
            "RELIANCE": [
                _make_bar("RELIANCE", "2024-01-15T09:30:00"),
                _make_bar("RELIANCE", "2024-01-15T09:32:00"),
            ],
        }
        feed = PaperMarketFeed(bars)
        result = list(feed.iter_bars())
        timestamps = [r[0] for r in result]
        assert timestamps == sorted(timestamps)

    def test_tie_broken_by_symbol_alphabetically(self):
        # Both bars have the same timestamp — should sort by symbol name.
        ts = "2024-01-15T09:30:00"
        bars = {
            "TCS": [_make_bar("TCS", ts)],
            "RELIANCE": [_make_bar("RELIANCE", ts)],
        }
        feed = PaperMarketFeed(bars)
        result = list(feed.iter_bars())
        # RELIANCE < TCS alphabetically
        assert result[0][1] == "RELIANCE"
        assert result[1][1] == "TCS"

    def test_total_bar_count_across_symbols(self):
        bars = {
            "A": [_make_bar("A", f"2024-01-15T09:{30 + i:02d}:00") for i in range(3)],
            "B": [_make_bar("B", f"2024-01-15T09:{30 + i:02d}:00") for i in range(2)],
        }
        feed = PaperMarketFeed(bars)
        result = list(feed.iter_bars())
        assert len(result) == 5


# ---------------------------------------------------------------------------
# Empty feed
# ---------------------------------------------------------------------------


class TestEmptyFeed:
    def test_empty_symbols_dict(self):
        feed = PaperMarketFeed({})
        result = list(feed.iter_bars())
        assert result == []

    def test_symbol_with_empty_bar_list(self):
        feed = PaperMarketFeed({"RELIANCE": []})
        result = list(feed.iter_bars())
        assert result == []

    def test_symbol_with_empty_dataframe(self):
        cols = ["timestamp", "open", "high", "low", "close", "volume"]
        df = pd.DataFrame(columns=cols)
        feed = PaperMarketFeed({"RELIANCE": df})
        result = list(feed.iter_bars())
        assert result == []


# ---------------------------------------------------------------------------
# reset() is safe
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_is_safe(self):
        bars = [_make_bar("RELIANCE", "2024-01-15T09:30:00")]
        feed = PaperMarketFeed({"RELIANCE": bars})
        list(feed.iter_bars())
        feed.reset()  # Should not raise
        result = list(feed.iter_bars())
        assert len(result) == 1  # Can iterate again after reset


# ---------------------------------------------------------------------------
# Mixed input types
# ---------------------------------------------------------------------------


class TestMixedInputTypes:
    def test_accepts_bar_list(self):
        bars = [_make_bar("RELIANCE", "2024-01-15T09:30:00")]
        feed = PaperMarketFeed({"RELIANCE": bars})
        assert len(list(feed.iter_bars())) == 1

    def test_accepts_dataframe(self):
        df = _make_df(["2024-01-15 09:30:00"])
        feed = PaperMarketFeed({"RELIANCE": df})
        assert len(list(feed.iter_bars())) == 1
