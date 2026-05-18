"""Tests for live_data.zerodha_feed — ZerodhaLiveMarketFeed with fake ticker."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trading_engine.live_data.models import LiveTick
from trading_engine.live_data.zerodha_feed import (
    ZerodhaLiveMarketFeed,
    _raw_tick_to_live_tick,
)

_TOKEN = 256265
_SYM = "RELIANCE"

# ---------------------------------------------------------------------------
# Fake KiteTicker
# ---------------------------------------------------------------------------


class FakeTicker:
    """Minimal KiteTicker-like fake for unit tests. No real WebSocket."""

    MODE_FULL = "full"
    MODE_QUOTE = "quote"
    MODE_LTP = "ltp"

    def __init__(self) -> None:
        self.on_ticks = None
        self.on_connect = None
        self.on_close = None
        self.on_error = None
        self._connected = False
        self._subscribed: list[int] = []
        self._mode_calls: list[tuple[str, list[int]]] = []
        self.connect_called = False
        self.close_called = False

    def connect(self, threaded: bool = True) -> None:  # noqa: ARG002
        self.connect_called = True
        self._connected = True
        # Simulate on_connect being fired.
        if self.on_connect:
            self.on_connect(self, {})

    def close(self) -> None:
        self.close_called = True
        self._connected = False
        if self.on_close:
            self.on_close(self, 1000, "normal")

    def subscribe(self, tokens: list[int]) -> None:
        self._subscribed.extend(tokens)

    def set_mode(self, mode: str, tokens: list[int]) -> None:
        self._mode_calls.append((mode, tokens))

    def fire_ticks(self, ticks: list[dict]) -> None:
        """Helper: manually fire the on_ticks callback with given tick dicts."""
        if self.on_ticks:
            self.on_ticks(self, ticks)


def _make_feed(
    tokens: list[int] | None = None,
    token_symbol_map: dict[int, str] | None = None,
) -> tuple[ZerodhaLiveMarketFeed, FakeTicker]:
    fake_ticker = FakeTicker()

    def factory(api_key: str, access_token: str) -> FakeTicker:  # noqa: ARG001
        return fake_ticker

    feed = ZerodhaLiveMarketFeed(
        kite_ticker_factory=factory,
        api_key="fake_key",
        access_token="fake_token",
        instrument_tokens=tokens or [_TOKEN],
        token_symbol_map=token_symbol_map or {_TOKEN: _SYM},
    )
    return feed, fake_ticker


def _raw_tick(
    token: int = _TOKEN,
    price: float = 2345.0,
    volume: int | None = 1000,
    ts: datetime | None = None,
) -> dict:
    return {
        "instrument_token": token,
        "last_price": price,
        "volume_traded": volume,
        "average_traded_price": price,
        "exchange_timestamp": ts or datetime(2024, 1, 15, 9, 15, 30),
    }


# ---------------------------------------------------------------------------
# _raw_tick_to_live_tick helper
# ---------------------------------------------------------------------------


class TestRawTickToLiveTick:
    def test_valid_tick_converts(self):
        raw = _raw_tick()
        tick = _raw_tick_to_live_tick(raw, {_TOKEN: _SYM})
        assert tick is not None
        assert tick.instrument_token == _TOKEN
        assert tick.last_price == Decimal("2345.0")
        assert tick.symbol == _SYM

    def test_missing_instrument_token_returns_none(self):
        raw = {"last_price": 100.0}
        assert _raw_tick_to_live_tick(raw, {}) is None

    def test_missing_last_price_returns_none(self):
        raw = {"instrument_token": 1}
        assert _raw_tick_to_live_tick(raw, {}) is None

    def test_zero_last_price_returns_none(self):
        raw = _raw_tick(price=0.0)
        assert _raw_tick_to_live_tick(raw, {_TOKEN: _SYM}) is None

    def test_no_symbol_map_symbol_is_none(self):
        raw = _raw_tick()
        tick = _raw_tick_to_live_tick(raw, None)
        assert tick is not None
        assert tick.symbol is None

    def test_volume_traded_key_used(self):
        raw = _raw_tick(volume=5000)
        tick = _raw_tick_to_live_tick(raw, {_TOKEN: _SYM})
        assert tick.volume == 5000

    def test_volume_key_fallback(self):
        raw = {
            "instrument_token": _TOKEN,
            "last_price": 100.0,
            "volume": 999,
            "exchange_timestamp": datetime(2024, 1, 15, 9, 15, 0),
        }
        tick = _raw_tick_to_live_tick(raw, {_TOKEN: _SYM})
        assert tick is not None
        assert tick.volume == 999

    def test_average_traded_price_parsed(self):
        raw = _raw_tick()
        tick = _raw_tick_to_live_tick(raw, {_TOKEN: _SYM})
        assert tick is not None
        assert tick.average_price == Decimal("2345.0")

    def test_raw_dict_attached(self):
        raw = _raw_tick()
        tick = _raw_tick_to_live_tick(raw, {_TOKEN: _SYM})
        assert tick is not None
        assert tick.raw is raw

    def test_exchange_timestamp_used(self):
        ts = datetime(2024, 1, 15, 9, 30, 0)
        raw = _raw_tick(ts=ts)
        tick = _raw_tick_to_live_tick(raw, {})
        assert tick is not None
        assert tick.timestamp == ts

    def test_fallback_timestamp_when_no_timestamp_key(self):
        raw = {"instrument_token": 1, "last_price": 100.0}
        tick = _raw_tick_to_live_tick(raw, {})
        assert tick is not None
        # Should have some fallback timestamp (UTC now)
        assert isinstance(tick.timestamp, datetime)


# ---------------------------------------------------------------------------
# ZerodhaLiveMarketFeed
# ---------------------------------------------------------------------------


class TestFeedInit:
    def test_feed_created_with_factory(self):
        feed, _ = _make_feed()
        assert feed is not None

    def test_not_connected_initially(self):
        feed, _ = _make_feed()
        assert feed.is_connected() is False

    def test_ticker_callbacks_wired(self):
        feed, ticker = _make_feed()
        assert ticker.on_ticks is not None
        assert ticker.on_connect is not None
        assert ticker.on_close is not None
        assert ticker.on_error is not None


class TestConnectDisconnect:
    def test_connect_calls_ticker_connect(self):
        feed, ticker = _make_feed()
        feed.connect()
        assert ticker.connect_called is True

    def test_connect_marks_connected(self):
        feed, _ = _make_feed()
        feed.connect()
        assert feed.is_connected() is True

    def test_connect_subscribes_tokens(self):
        feed, ticker = _make_feed(tokens=[_TOKEN, 12345])
        feed.connect()
        assert _TOKEN in ticker._subscribed
        assert 12345 in ticker._subscribed

    def test_disconnect_calls_close(self):
        feed, ticker = _make_feed()
        feed.connect()
        feed.disconnect()
        assert ticker.close_called is True

    def test_disconnect_marks_not_connected(self):
        feed, _ = _make_feed()
        feed.connect()
        feed.disconnect()
        assert feed.is_connected() is False


class TestTickCallback:
    def test_callback_receives_live_tick(self):
        feed, ticker = _make_feed()
        received: list[LiveTick] = []
        feed.set_tick_callback(received.append)
        feed.connect()
        ticker.fire_ticks([_raw_tick()])
        assert len(received) == 1
        assert isinstance(received[0], LiveTick)

    def test_callback_has_correct_price(self):
        feed, ticker = _make_feed()
        received: list[LiveTick] = []
        feed.set_tick_callback(received.append)
        feed.connect()
        ticker.fire_ticks([_raw_tick(price=2500.0)])
        assert received[0].last_price == Decimal("2500.0")

    def test_callback_resolves_symbol(self):
        feed, ticker = _make_feed(token_symbol_map={_TOKEN: "RELIANCE"})
        received: list[LiveTick] = []
        feed.set_tick_callback(received.append)
        feed.connect()
        ticker.fire_ticks([_raw_tick(token=_TOKEN)])
        assert received[0].symbol == "RELIANCE"

    def test_multiple_ticks_in_one_batch(self):
        feed, ticker = _make_feed(
            tokens=[_TOKEN, 12345],
            token_symbol_map={_TOKEN: "RELIANCE", 12345: "INFY"},
        )
        received: list[LiveTick] = []
        feed.set_tick_callback(received.append)
        feed.connect()
        ticker.fire_ticks([_raw_tick(_TOKEN), _raw_tick(12345, 1500.0)])
        assert len(received) == 2

    def test_invalid_tick_skipped(self):
        feed, ticker = _make_feed()
        received: list[LiveTick] = []
        feed.set_tick_callback(received.append)
        feed.connect()
        ticker.fire_ticks([{"instrument_token": _TOKEN}])  # missing last_price
        assert len(received) == 0

    def test_no_callback_does_not_raise(self):
        feed, ticker = _make_feed()
        feed.connect()
        # No callback set — should not raise.
        ticker.fire_ticks([_raw_tick()])

    def test_callback_exception_is_caught(self):
        feed, ticker = _make_feed()

        def bad_callback(tick: LiveTick) -> None:
            raise RuntimeError("bad callback")

        feed.set_tick_callback(bad_callback)
        feed.connect()
        # Should not propagate the exception.
        ticker.fire_ticks([_raw_tick()])

    def test_on_close_marks_disconnected(self):
        feed, ticker = _make_feed()
        feed.connect()
        ticker.close()
        assert feed.is_connected() is False


class TestSubscribe:
    def test_subscribe_additional_tokens(self):
        feed, ticker = _make_feed()
        feed.connect()
        feed.subscribe([99999])
        assert 99999 in ticker._subscribed
