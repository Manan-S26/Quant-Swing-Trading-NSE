"""Zerodha live market data feed.

Thin wrapper around a KiteTicker-like object (injected via factory).
Converts raw Zerodha tick dicts into LiveTick objects and forwards them
to a registered callback.

Design notes:
- KiteTicker is NOT imported at the module level. The caller supplies a
  factory function so that tests can inject a fake ticker without installing
  or connecting to pykiteconnect.
- This class does NOT place orders and does NOT import any order APIs.
- Real WebSocket connections are never opened in unit tests.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from trading_engine.live_data.models import LiveTick


def _parse_timestamp(raw: dict[str, Any]) -> datetime:
    """Extract the best available timestamp from a raw Zerodha tick dict.

    Zerodha KiteTicker provides exchange_timestamp and last_trade_time.
    Falls back to UTC now if neither is present.
    """
    for key in ("exchange_timestamp", "last_trade_time"):
        value = raw.get(key)
        if isinstance(value, datetime):
            return value
    # Final fallback — should never happen with a real KiteTicker.
    return datetime.now(tz=UTC)


def _raw_tick_to_live_tick(
    raw: dict[str, Any],
    token_symbol_map: dict[int, str] | None,
) -> LiveTick | None:
    """Convert a raw Zerodha tick dict to a LiveTick.

    Returns None if the tick is missing required fields or has an invalid price.
    """
    try:
        token = int(raw["instrument_token"])
        last_price = Decimal(str(raw["last_price"]))
    except (KeyError, TypeError, ValueError):
        return None

    symbol = (token_symbol_map or {}).get(token)

    volume = raw.get("volume_traded") or raw.get("volume")
    try:
        volume = int(volume) if volume is not None else None
    except (TypeError, ValueError):
        volume = None

    avg_raw = raw.get("average_traded_price") or raw.get("average_price")
    try:
        average_price = Decimal(str(avg_raw)) if avg_raw is not None else None
    except (TypeError, ValueError):
        average_price = None

    ts = _parse_timestamp(raw)

    try:
        return LiveTick(
            instrument_token=token,
            symbol=symbol,
            exchange=None,  # Zerodha ticks don't include exchange in tick data
            timestamp=ts,
            last_price=last_price,
            volume=volume,
            average_price=average_price,
            raw=raw,
        )
    except ValueError:
        # Validation failed (e.g. last_price <= 0 for a malformed tick).
        return None


class ZerodhaLiveMarketFeed:
    """Connects to a KiteTicker-like WebSocket and emits LiveTick objects.

    The KiteTicker object is created by calling ``kite_ticker_factory(api_key,
    access_token)``.  This factory pattern allows unit tests to inject a
    fake ticker without any real network activity.

    Args:
        kite_ticker_factory: Callable that accepts (api_key, access_token) and
                             returns a KiteTicker-compatible object. The returned
                             object must implement:
                               - on_ticks callback attribute (or similar)
                               - on_connect, on_close, on_error callback attributes
                               - connect(threaded=True) method
                               - close() method
                               - subscribe(tokens) method
                               - set_mode(mode, tokens) method
        api_key:             Zerodha API key string.
        access_token:        Zerodha access token string.
        instrument_tokens:   List of instrument tokens to subscribe to.
        token_symbol_map:    Optional mapping of instrument_token → symbol string.
        logger:              Optional logger override.
    """

    def __init__(
        self,
        kite_ticker_factory: Callable[[str, str], Any],
        api_key: str,
        access_token: str,
        instrument_tokens: list[int],
        token_symbol_map: dict[int, str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._instrument_tokens = list(instrument_tokens)
        self._token_symbol_map = token_symbol_map or {}
        self._logger = logger or logging.getLogger(__name__)
        self._tick_callback: Callable[[LiveTick], None] | None = None
        self._connected = False

        # Create the ticker via the injected factory — no real connection yet.
        self._ticker = kite_ticker_factory(api_key, access_token)
        self._wire_ticker_callbacks()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_tick_callback(self, callback: Callable[[LiveTick], None]) -> None:
        """Register the function to call for each LiveTick received."""
        self._tick_callback = callback

    def connect(self) -> None:
        """Start the WebSocket connection (non-blocking / threaded)."""
        self._logger.info(
            "ZerodhaLiveMarketFeed: connecting — tokens=%s",
            self._instrument_tokens,
        )
        self._ticker.connect(threaded=True)

    def disconnect(self) -> None:
        """Close the WebSocket connection."""
        self._logger.info("ZerodhaLiveMarketFeed: disconnecting.")
        self._ticker.close()
        self._connected = False

    def subscribe(self, tokens: list[int]) -> None:
        """Subscribe to additional instrument tokens after connecting."""
        self._ticker.subscribe(tokens)
        self._ticker.set_mode(self._ticker.MODE_FULL, tokens)

    def is_connected(self) -> bool:
        """Return True if the WebSocket is currently connected."""
        return self._connected

    # ------------------------------------------------------------------
    # Internal — wire KiteTicker callbacks
    # ------------------------------------------------------------------

    def _wire_ticker_callbacks(self) -> None:
        self._ticker.on_ticks = self._on_ticks
        self._ticker.on_connect = self._on_connect
        self._ticker.on_close = self._on_close
        self._ticker.on_error = self._on_error

    def _on_connect(self, ws: Any, response: Any) -> None:  # noqa: ARG002
        self._connected = True
        self._logger.info("ZerodhaLiveMarketFeed: WebSocket connected.")
        if self._instrument_tokens:
            self.subscribe(self._instrument_tokens)

    def _on_ticks(self, ws: Any, ticks: list[dict[str, Any]]) -> None:  # noqa: ARG002
        if self._tick_callback is None:
            return
        for raw in ticks:
            live_tick = _raw_tick_to_live_tick(raw, self._token_symbol_map)
            if live_tick is not None:
                try:
                    self._tick_callback(live_tick)
                except Exception:
                    self._logger.exception(
                        "Error in tick callback for token=%s",
                        raw.get("instrument_token"),
                    )

    def _on_close(self, ws: Any, code: int, reason: str) -> None:  # noqa: ARG002
        self._connected = False
        self._logger.warning(
            "ZerodhaLiveMarketFeed: WebSocket closed — code=%s reason=%s",
            code,
            reason,
        )

    def _on_error(self, ws: Any, code: int, reason: str) -> None:  # noqa: ARG002
        self._logger.error(
            "ZerodhaLiveMarketFeed: WebSocket error — code=%s reason=%s",
            code,
            reason,
        )
