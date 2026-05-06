"""Tests for HistoricalDataDownloader."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from trading_engine.data.historical import HistoricalDataDownloader
from trading_engine.data.universe import UniverseConfig
from trading_engine.domain.enums import Exchange


# ---------------------------------------------------------------------------
# Fake broker
# ---------------------------------------------------------------------------

def _make_raw_candle(
    date: datetime | None = None,
    open_: float = 2800.0,
    high: float = 2820.0,
    low: float = 2790.0,
    close: float = 2810.0,
    volume: int = 10000,
) -> dict:
    return {
        "date": date or datetime(2024, 1, 15, 9, 15),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


class FakeBroker:
    """Broker stub that returns configurable candle data."""

    def __init__(self, candles: list[dict] | None = None) -> None:
        self._candles = candles if candles is not None else [
            _make_raw_candle(datetime(2024, 1, 15, 9, 15)),
            _make_raw_candle(datetime(2024, 1, 15, 9, 16)),
            _make_raw_candle(datetime(2024, 1, 15, 9, 17)),
        ]
        self.calls: list[dict] = []

    def get_historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
    ) -> list[dict]:
        self.calls.append({
            "instrument_token": instrument_token,
            "from_date": from_date,
            "to_date": to_date,
            "interval": interval,
        })
        return self._candles


def _make_downloader(
    tmp_path: Path,
    candles: list[dict] | None = None,
) -> tuple[HistoricalDataDownloader, FakeBroker]:
    broker = FakeBroker(candles)
    downloader = HistoricalDataDownloader(broker=broker, data_dir=tmp_path)
    return downloader, broker


# ---------------------------------------------------------------------------
# DataFrame structure
# ---------------------------------------------------------------------------

class TestDownloadDataFrame:
    def test_returns_dataframe(self, tmp_path: Path) -> None:
        downloader, _ = _make_downloader(tmp_path)
        df, _ = downloader.download(
            instrument_token=738561,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        assert isinstance(df, pd.DataFrame)

    def test_dataframe_has_required_columns(self, tmp_path: Path) -> None:
        downloader, _ = _make_downloader(tmp_path)
        df, _ = downloader.download(
            instrument_token=738561,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        for col in ("timestamp", "open", "high", "low", "close", "volume"):
            assert col in df.columns, f"Missing column: {col}"

    def test_dataframe_does_not_have_date_column(self, tmp_path: Path) -> None:
        downloader, _ = _make_downloader(tmp_path)
        df, _ = downloader.download(
            instrument_token=738561,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        assert "date" not in df.columns

    def test_dataframe_row_count_matches_candles(self, tmp_path: Path) -> None:
        candles = [
            _make_raw_candle(datetime(2024, 1, 15, 9, 15)),
            _make_raw_candle(datetime(2024, 1, 15, 9, 16)),
        ]
        downloader, _ = _make_downloader(tmp_path, candles)
        df, _ = downloader.download(
            instrument_token=738561,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        assert len(df) == 2

    def test_volume_is_integer_dtype(self, tmp_path: Path) -> None:
        downloader, _ = _make_downloader(tmp_path)
        df, _ = downloader.download(
            instrument_token=738561,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        assert pd.api.types.is_integer_dtype(df["volume"])

    def test_price_columns_are_numeric(self, tmp_path: Path) -> None:
        downloader, _ = _make_downloader(tmp_path)
        df, _ = downloader.download(
            instrument_token=738561,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        for col in ("open", "high", "low", "close"):
            assert pd.api.types.is_numeric_dtype(df[col]), f"{col} is not numeric"


# ---------------------------------------------------------------------------
# Parquet save behaviour
# ---------------------------------------------------------------------------

class TestParquetSave:
    def test_save_true_creates_parquet_file(self, tmp_path: Path) -> None:
        downloader, _ = _make_downloader(tmp_path)
        downloader.download(
            instrument_token=738561,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=True,
        )
        expected = tmp_path / "candles" / "NSE" / "RELIANCE" / "minute.parquet"
        assert expected.exists()

    def test_save_false_does_not_create_parquet_file(self, tmp_path: Path) -> None:
        downloader, _ = _make_downloader(tmp_path)
        downloader.download(
            instrument_token=738561,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        expected = tmp_path / "candles" / "NSE" / "RELIANCE" / "minute.parquet"
        assert not expected.exists()

    def test_saved_parquet_is_readable(self, tmp_path: Path) -> None:
        downloader, _ = _make_downloader(tmp_path)
        df_orig, _ = downloader.download(
            instrument_token=738561,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=True,
        )
        path = tmp_path / "candles" / "NSE" / "RELIANCE" / "minute.parquet"
        df_read = pd.read_parquet(path)
        assert len(df_read) == len(df_orig)


# ---------------------------------------------------------------------------
# get_candle_file_path
# ---------------------------------------------------------------------------

class TestGetCandleFilePath:
    def test_returns_correct_path(self, tmp_path: Path) -> None:
        downloader, _ = _make_downloader(tmp_path)
        path = downloader.get_candle_file_path("RELIANCE", Exchange.NSE, "minute")
        assert path == tmp_path / "candles" / "NSE" / "RELIANCE" / "minute.parquet"

    def test_different_intervals_give_different_paths(self, tmp_path: Path) -> None:
        downloader, _ = _make_downloader(tmp_path)
        p1 = downloader.get_candle_file_path("INFY", Exchange.NSE, "minute")
        p2 = downloader.get_candle_file_path("INFY", Exchange.NSE, "5minute")
        assert p1 != p2


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------

class TestValidationReport:
    def test_returns_data_validation_report(self, tmp_path: Path) -> None:
        from trading_engine.data.validation import DataValidationReport

        downloader, _ = _make_downloader(tmp_path)
        _, report = downloader.download(
            instrument_token=738561,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        assert isinstance(report, DataValidationReport)

    def test_valid_candles_produce_valid_report(self, tmp_path: Path) -> None:
        downloader, _ = _make_downloader(tmp_path)
        _, report = downloader.download(
            instrument_token=738561,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        assert report.is_valid is True

    def test_report_symbol_and_exchange(self, tmp_path: Path) -> None:
        downloader, _ = _make_downloader(tmp_path)
        _, report = downloader.download(
            instrument_token=738561,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        assert report.symbol == "RELIANCE"
        assert report.exchange == Exchange.NSE


# ---------------------------------------------------------------------------
# Empty candle response
# ---------------------------------------------------------------------------

class TestEmptyCandles:
    def test_empty_response_returns_empty_dataframe(self, tmp_path: Path) -> None:
        downloader, _ = _make_downloader(tmp_path, candles=[])
        df, _ = downloader.download(
            instrument_token=738561,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        assert len(df) == 0

    def test_empty_response_has_correct_columns(self, tmp_path: Path) -> None:
        downloader, _ = _make_downloader(tmp_path, candles=[])
        df, _ = downloader.download(
            instrument_token=738561,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        for col in ("timestamp", "open", "high", "low", "close", "volume"):
            assert col in df.columns

    def test_empty_response_report_is_invalid(self, tmp_path: Path) -> None:
        downloader, _ = _make_downloader(tmp_path, candles=[])
        _, report = downloader.download(
            instrument_token=738561,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        assert report.is_valid is False


# ---------------------------------------------------------------------------
# Broker call forwarding
# ---------------------------------------------------------------------------

class TestBrokerCallForwarding:
    def test_broker_called_with_correct_token(self, tmp_path: Path) -> None:
        downloader, broker = _make_downloader(tmp_path)
        downloader.download(
            instrument_token=999999,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        assert broker.calls[0]["instrument_token"] == 999999

    def test_broker_called_with_correct_interval(self, tmp_path: Path) -> None:
        downloader, broker = _make_downloader(tmp_path)
        downloader.download(
            instrument_token=738561,
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            interval="5minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        assert broker.calls[0]["interval"] == "5minute"


# ---------------------------------------------------------------------------
# download_universe
# ---------------------------------------------------------------------------

class TestDownloadUniverse:
    def test_downloads_all_symbols_in_universe(self, tmp_path: Path) -> None:
        downloader, _ = _make_downloader(tmp_path)
        universe = UniverseConfig(
            name="test",
            symbols=["RELIANCE", "INFY"],
            exchange=Exchange.NSE,
        )
        instruments = {"RELIANCE": 738561, "INFY": 408065}
        results = downloader.download_universe(
            instruments=instruments,
            universe=universe,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        assert "RELIANCE" in results
        assert "INFY" in results

    def test_skips_symbols_without_token(self, tmp_path: Path) -> None:
        downloader, _ = _make_downloader(tmp_path)
        universe = UniverseConfig(
            name="test",
            symbols=["RELIANCE", "INFY"],
            exchange=Exchange.NSE,
        )
        instruments = {"RELIANCE": 738561}  # INFY missing
        results = downloader.download_universe(
            instruments=instruments,
            universe=universe,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        assert "RELIANCE" in results
        assert "INFY" not in results

    def test_returns_tuple_of_df_and_report(self, tmp_path: Path) -> None:
        from trading_engine.data.validation import DataValidationReport

        downloader, _ = _make_downloader(tmp_path)
        universe = UniverseConfig(
            name="test",
            symbols=["RELIANCE"],
            exchange=Exchange.NSE,
        )
        results = downloader.download_universe(
            instruments={"RELIANCE": 738561},
            universe=universe,
            interval="minute",
            from_date=datetime(2024, 1, 15),
            to_date=datetime(2024, 1, 15),
            save=False,
        )
        df, report = results["RELIANCE"]
        assert isinstance(df, pd.DataFrame)
        assert isinstance(report, DataValidationReport)
