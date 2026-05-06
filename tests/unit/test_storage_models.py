"""Tests for SQLAlchemy ORM storage models."""

from __future__ import annotations

from datetime import datetime

from trading_engine.storage.models import HistoricalCandlesMetadata


class TestHistoricalCandlesMetadata:
    def test_tablename(self) -> None:
        assert HistoricalCandlesMetadata.__tablename__ == "historical_candles_metadata"

    def test_has_id_column(self) -> None:
        assert hasattr(HistoricalCandlesMetadata, "id")

    def test_has_symbol_column(self) -> None:
        assert hasattr(HistoricalCandlesMetadata, "symbol")

    def test_has_exchange_column(self) -> None:
        assert hasattr(HistoricalCandlesMetadata, "exchange")

    def test_has_interval_column(self) -> None:
        assert hasattr(HistoricalCandlesMetadata, "interval")

    def test_has_from_date_column(self) -> None:
        assert hasattr(HistoricalCandlesMetadata, "from_date")

    def test_has_to_date_column(self) -> None:
        assert hasattr(HistoricalCandlesMetadata, "to_date")

    def test_has_candle_count_column(self) -> None:
        assert hasattr(HistoricalCandlesMetadata, "candle_count")

    def test_has_file_path_column(self) -> None:
        assert hasattr(HistoricalCandlesMetadata, "file_path")

    def test_has_downloaded_at_column(self) -> None:
        assert hasattr(HistoricalCandlesMetadata, "downloaded_at")

    def test_has_is_valid_column(self) -> None:
        assert hasattr(HistoricalCandlesMetadata, "is_valid")

    def test_repr_contains_symbol(self) -> None:
        row = HistoricalCandlesMetadata(
            symbol="RELIANCE",
            exchange="NSE",
            interval="minute",
            from_date=datetime(2024, 1, 1),
            to_date=datetime(2024, 1, 31),
            candle_count=5000,
            file_path="/data/candles/NSE/RELIANCE/minute.parquet",
            downloaded_at=datetime(2024, 2, 1, 12, 0),
            is_valid=True,
        )
        assert "RELIANCE" in repr(row)

    def test_repr_contains_is_valid(self) -> None:
        row = HistoricalCandlesMetadata(
            symbol="INFY",
            exchange="NSE",
            interval="day",
            from_date=datetime(2024, 1, 1),
            to_date=datetime(2024, 1, 31),
            candle_count=20,
            file_path="/data/candles/NSE/INFY/day.parquet",
            downloaded_at=datetime(2024, 2, 1, 12, 0),
            is_valid=False,
        )
        assert "is_valid=False" in repr(row)

    def test_model_stores_attributes(self) -> None:
        row = HistoricalCandlesMetadata(
            symbol="TCS",
            exchange="NSE",
            interval="5minute",
            from_date=datetime(2024, 1, 1),
            to_date=datetime(2024, 1, 31),
            candle_count=1200,
            file_path="/data/candles/NSE/TCS/5minute.parquet",
            downloaded_at=datetime(2024, 2, 1, 12, 0),
            is_valid=True,
        )
        assert row.symbol == "TCS"
        assert row.exchange == "NSE"
        assert row.interval == "5minute"
        assert row.candle_count == 1200
        assert row.is_valid is True
