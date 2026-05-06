"""Historical candle downloader.

Downloads OHLCV data from a broker, normalises it into a pandas DataFrame,
validates it, and saves it as Parquet.

Usage:
    downloader = HistoricalDataDownloader(broker=zerodha_broker, data_dir="data/")
    df, report = downloader.download(
        instrument_token=738561,
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval="minute",
        from_date=datetime(2024, 1, 1),
        to_date=datetime(2024, 1, 31),
    )

Storage layout:
    DATA_DIR/candles/{exchange}/{symbol}/{interval}.parquet
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from trading_engine.data.universe import UniverseConfig
from trading_engine.data.validation import DataValidationReport, validate_ohlcv_dataframe
from trading_engine.domain.enums import Exchange

logger = logging.getLogger(__name__)

# Zerodha API returns "date" for the timestamp column.  We normalise to "timestamp".
_ZERODHA_DATE_COL = "date"
_NUMERIC_COLS = ("open", "high", "low", "close")


class HistoricalDataDownloader:
    """Downloads and stores historical OHLCV candle data.

    The broker is injected so this class works with any Broker-compatible
    implementation (ZerodhaBroker, a fake, etc.) without code changes.

    Args:
        broker:   Any object that implements get_historical_data().
        data_dir: Root directory for Parquet storage.
        logger:   Optional logger; defaults to module logger.
    """

    def __init__(
        self,
        broker: Any,
        data_dir: str | Path,
        logger: logging.Logger | None = None,
    ) -> None:
        self._broker = broker
        self._data_dir = Path(data_dir)
        self._logger = logger or logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def download(
        self,
        instrument_token: int,
        symbol: str,
        exchange: Exchange | str,
        interval: str,
        from_date: datetime,
        to_date: datetime,
        save: bool = True,
    ) -> tuple[pd.DataFrame, DataValidationReport]:
        """Download candles for one symbol and optionally save as Parquet.

        Args:
            instrument_token: Zerodha integer instrument token.
            symbol:           Trading symbol, e.g. "RELIANCE".
            exchange:         Exchange enum or string, e.g. Exchange.NSE.
            interval:         Candle interval: "minute", "5minute", "day", etc.
            from_date:        Start of the date range.
            to_date:          End of the date range.
            save:             If True, write the DataFrame to Parquet.

        Returns:
            (DataFrame, DataValidationReport) tuple.
        """
        exch = Exchange(exchange) if isinstance(exchange, str) else exchange
        self._logger.info(
            "Downloading %s %s %s %s → %s",
            symbol,
            exch,
            interval,
            from_date.date(),
            to_date.date(),
        )

        raw: list[dict[str, Any]] = self._broker.get_historical_data(
            instrument_token=instrument_token,
            from_date=from_date,
            to_date=to_date,
            interval=interval,
        )

        df = self._to_dataframe(raw)
        report = validate_ohlcv_dataframe(df, symbol, exch, interval)

        if report.is_valid:
            self._logger.info(
                "Downloaded %d candles for %s [%s]. Valid.",
                report.row_count,
                symbol,
                interval,
            )
        else:
            error_codes = [i.code for i in report.issues if i.severity == "error"]
            self._logger.warning(
                "Downloaded %d candles for %s [%s]. Validation errors: %s",
                report.row_count,
                symbol,
                interval,
                error_codes,
            )

        if save:
            path = self.get_candle_file_path(symbol, exch, interval)
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(path, index=False)
            self._logger.info("Saved candles → %s", path)

        return df, report

    def download_universe(
        self,
        instruments: dict[str, int],
        universe: UniverseConfig,
        interval: str,
        from_date: datetime,
        to_date: datetime,
        save: bool = True,
    ) -> dict[str, tuple[pd.DataFrame, DataValidationReport]]:
        """Download candles for every symbol in the universe.

        Args:
            instruments: Mapping of symbol → instrument_token.
            universe:    UniverseConfig defining the symbol list and exchange.
            interval:    Candle interval.
            from_date:   Start of date range.
            to_date:     End of date range.
            save:        If True, write each symbol's DataFrame to Parquet.

        Returns:
            Dict of symbol → (DataFrame, DataValidationReport).
        """
        results: dict[str, tuple[pd.DataFrame, DataValidationReport]] = {}
        for symbol in universe.get_symbols():
            if symbol not in instruments:
                self._logger.warning("No instrument_token found for %s — skipping.", symbol)
                continue
            df, report = self.download(
                instrument_token=instruments[symbol],
                symbol=symbol,
                exchange=universe.exchange,
                interval=interval,
                from_date=from_date,
                to_date=to_date,
                save=save,
            )
            results[symbol] = (df, report)
        return results

    def get_candle_file_path(
        self,
        symbol: str,
        exchange: Exchange | str,
        interval: str,
    ) -> Path:
        """Return the Parquet file path for a given symbol/exchange/interval.

        Layout: DATA_DIR/candles/{exchange}/{symbol}/{interval}.parquet
        """
        return self._data_dir / "candles" / str(exchange) / symbol / f"{interval}.parquet"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _to_dataframe(self, raw: list[dict[str, Any]]) -> pd.DataFrame:
        """Convert a list of Zerodha candle dicts to a normalised DataFrame.

        Zerodha returns dicts with key "date" for the timestamp. This renames
        it to "timestamp" and ensures numeric dtypes for OHLCV columns.
        """
        if not raw:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(raw)

        # Rename "date" → "timestamp" (Zerodha API convention).
        if _ZERODHA_DATE_COL in df.columns and "timestamp" not in df.columns:
            df = df.rename(columns={_ZERODHA_DATE_COL: "timestamp"})

        # Ensure numeric types for price columns.
        for col in _NUMERIC_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Volume as integer where possible.
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")

        return df
