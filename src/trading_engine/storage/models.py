"""SQLAlchemy ORM models for the trading engine.

Only the metadata table is defined here in Milestone 4.
Full schema (orders, trades, positions, etc.) will be added in later milestones.

Do not instantiate these models or run migrations without calling init_db() first.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from trading_engine.storage.database import Base


class HistoricalCandlesMetadata(Base):
    """Tracks downloaded candle files and their validation status.

    One row per (symbol, exchange, interval) download run.
    The file_path points to the Parquet file on disk.
    """

    __tablename__ = "historical_candles_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    interval: Mapped[str] = mapped_column(String(20), nullable=False)
    from_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    to_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    candle_count: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return (
            f"HistoricalCandlesMetadata("
            f"symbol={self.symbol!r}, exchange={self.exchange!r}, "
            f"interval={self.interval!r}, candle_count={self.candle_count}, "
            f"is_valid={self.is_valid})"
        )
