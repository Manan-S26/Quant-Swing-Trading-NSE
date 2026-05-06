"""Zerodha Kite Connect broker adapter — read-only.

Wraps the KiteConnect SDK behind the abstract Broker interface.
All order placement methods remain blocked.

Design decisions:
  - The KiteConnect client is injected via __init__; never created here.
  - This class does NOT store credentials directly. The caller is responsible
    for initialising the Kite client with a valid access_token before calling
    connect().
  - Live order placement raises LiveTradingDisabledError (inherited from Broker).
  - WebSocket streaming raises NotImplementedError; it will be implemented
    in a later milestone when live market data is required.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from trading_engine.broker.base import Broker
from trading_engine.common.exceptions import BrokerConnectionError
from trading_engine.domain.enums import Exchange


class ZerodhaBroker(Broker):
    """Zerodha Kite Connect broker adapter (read-only).

    Accepts a KiteConnect-compatible client via dependency injection so that
    tests can substitute a fake client without making real API calls.

    Args:
        kite_client: A KiteConnect instance (or compatible fake) with
                     positions(), orders(), trades(), margins(),
                     instruments(), historical_data(), and set_access_token().
        settings:    Optional Settings object (not used directly here;
                     use KiteAuthManager for credential management).
        logger:      Optional logger; defaults to module logger.

    Example:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=settings.zerodha_api_key.get_secret_value())
        kite.set_access_token(settings.zerodha_access_token.get_secret_value())
        broker = ZerodhaBroker(kite_client=kite, settings=settings)
        broker.connect()
    """

    def __init__(
        self,
        kite_client: Any,
        settings: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if kite_client is None:
            raise BrokerConnectionError("kite_client cannot be None. Pass a KiteConnect instance.")
        self._kite = kite_client
        self._settings = settings
        self._logger = logger or logging.getLogger(__name__)
        self._connected: bool = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Mark the broker as connected.

        In practice this means the Kite client has been configured with an
        access_token (via KiteAuthManager.generate_session or manually via
        kite.set_access_token). Call this before any data-fetching methods.
        """
        self._connected = True
        self._logger.info("ZerodhaBroker: connected.")

    def disconnect(self) -> None:
        """Mark the broker as disconnected."""
        self._connected = False
        self._logger.info("ZerodhaBroker: disconnected.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Internal guard
    # ------------------------------------------------------------------

    def _require_connected(self) -> None:
        if not self._connected:
            raise BrokerConnectionError(
                "ZerodhaBroker is not connected. Call connect() before fetching data."
            )

    # ------------------------------------------------------------------
    # Read-only account data
    # ------------------------------------------------------------------

    def get_positions(self) -> list[dict[str, Any]]:
        """Return raw positions dict from Zerodha.

        Zerodha returns {"net": [...], "day": [...]}.  The raw dict is passed
        through here; normalisation to internal Position models is done by
        mappers (future milestone).
        """
        self._require_connected()
        return self._kite.positions()  # type: ignore[no-any-return]

    def get_orders(self) -> list[dict[str, Any]]:
        """Return today's orders from Zerodha."""
        self._require_connected()
        return self._kite.orders()  # type: ignore[no-any-return]

    def get_trades(self) -> list[dict[str, Any]]:
        """Return today's executed trades from Zerodha."""
        self._require_connected()
        return self._kite.trades()  # type: ignore[no-any-return]

    def get_margins(self) -> dict[str, Any]:
        """Return margin and fund information from Zerodha."""
        self._require_connected()
        return self._kite.margins()  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Instrument and historical data (no connection guard — no session required)
    # ------------------------------------------------------------------

    def get_instruments(self, exchange: Exchange | str = Exchange.NSE) -> list[dict[str, Any]]:
        """Return the full instrument list for an exchange.

        This downloads a large CSV-backed list from Zerodha. Cache the result;
        do not call it on every bar.

        Args:
            exchange: Exchange enum or string, e.g. Exchange.NSE or "NSE".
        """
        return self._kite.instruments(str(exchange))  # type: ignore[no-any-return]

    def get_historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
    ) -> list[dict[str, Any]]:
        """Return historical OHLCV candles for an instrument.

        Args:
            instrument_token: Zerodha integer token for the instrument.
            from_date:        Start of the date range (datetime).
            to_date:          End of the date range (datetime).
            interval:         Candle interval, e.g. "minute", "5minute", "day".

        Returns:
            List of dicts with keys: date, open, high, low, close, volume.
        """
        return self._kite.historical_data(  # type: ignore[no-any-return]
            instrument_token=instrument_token,
            from_date=from_date,
            to_date=to_date,
            interval=interval,
        )

    # ------------------------------------------------------------------
    # Streaming — not yet implemented
    # ------------------------------------------------------------------

    def stream_ticks(self, symbols: list[str], callback: Any) -> None:
        """Live WebSocket tick streaming — not implemented in Milestone 3.

        Will be implemented in a later milestone when live market data is
        required (Milestone 8: Paper trading engine).

        Raises:
            NotImplementedError: always, until streaming is implemented.
        """
        raise NotImplementedError(
            "ZerodhaBroker.stream_ticks is not implemented in Milestone 3. "
            "WebSocket streaming will be added in a later milestone."
        )

    # ------------------------------------------------------------------
    # Order placement — BLOCKED (inherited from Broker base)
    # place_order, modify_order, cancel_order all raise LiveTradingDisabledError.
    # ------------------------------------------------------------------
