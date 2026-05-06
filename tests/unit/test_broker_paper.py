"""Tests for PaperBroker.

PaperBroker must never make real API calls and must block all order placement.
"""

from __future__ import annotations

import pytest

from trading_engine.broker.paper import PaperBroker
from trading_engine.common.exceptions import LiveTradingDisabledError


@pytest.fixture
def broker() -> PaperBroker:
    return PaperBroker()


@pytest.fixture
def connected_broker() -> PaperBroker:
    b = PaperBroker()
    b.connect()
    return b


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------

class TestPaperBrokerConnection:
    def test_not_connected_on_init(self, broker: PaperBroker) -> None:
        assert broker.is_connected is False

    def test_connect_marks_connected(self, broker: PaperBroker) -> None:
        broker.connect()
        assert broker.is_connected is True

    def test_disconnect_marks_disconnected(self, connected_broker: PaperBroker) -> None:
        connected_broker.disconnect()
        assert connected_broker.is_connected is False

    def test_connect_disconnect_cycle(self, broker: PaperBroker) -> None:
        broker.connect()
        assert broker.is_connected
        broker.disconnect()
        assert not broker.is_connected
        broker.connect()
        assert broker.is_connected


# ---------------------------------------------------------------------------
# Read-only methods return safe empty/default values
# ---------------------------------------------------------------------------

class TestPaperBrokerReadMethods:
    def test_get_positions_returns_empty_list(self, connected_broker: PaperBroker) -> None:
        assert connected_broker.get_positions() == []

    def test_get_orders_returns_empty_list(self, connected_broker: PaperBroker) -> None:
        assert connected_broker.get_orders() == []

    def test_get_trades_returns_empty_list(self, connected_broker: PaperBroker) -> None:
        assert connected_broker.get_trades() == []

    def test_get_margins_returns_empty_dict(self, connected_broker: PaperBroker) -> None:
        assert connected_broker.get_margins() == {}

    def test_get_positions_returns_list_type(self, connected_broker: PaperBroker) -> None:
        assert isinstance(connected_broker.get_positions(), list)

    def test_get_margins_returns_dict_type(self, connected_broker: PaperBroker) -> None:
        assert isinstance(connected_broker.get_margins(), dict)

    def test_read_methods_work_without_connect(self, broker: PaperBroker) -> None:
        # PaperBroker has no real connection to guard.
        assert broker.get_positions() == []
        assert broker.get_orders() == []
        assert broker.get_trades() == []
        assert broker.get_margins() == {}


# ---------------------------------------------------------------------------
# Streaming — not yet implemented
# ---------------------------------------------------------------------------

class TestPaperBrokerStreaming:
    def test_stream_ticks_raises_not_implemented(
        self, connected_broker: PaperBroker
    ) -> None:
        with pytest.raises(NotImplementedError, match="Milestone 8"):
            connected_broker.stream_ticks(["NSE:RELIANCE"], callback=lambda t: None)


# ---------------------------------------------------------------------------
# Order placement — must be blocked
# ---------------------------------------------------------------------------

class TestPaperBrokerOrdersBlocked:
    def test_place_order_raises_live_trading_disabled(
        self, connected_broker: PaperBroker
    ) -> None:
        with pytest.raises(LiveTradingDisabledError):
            connected_broker.place_order(
                tradingsymbol="RELIANCE", quantity=10, order_type="MARKET"
            )

    def test_modify_order_raises_live_trading_disabled(
        self, connected_broker: PaperBroker
    ) -> None:
        with pytest.raises(LiveTradingDisabledError):
            connected_broker.modify_order(order_id="abc", price=2850)

    def test_cancel_order_raises_live_trading_disabled(
        self, connected_broker: PaperBroker
    ) -> None:
        with pytest.raises(LiveTradingDisabledError):
            connected_broker.cancel_order(order_id="abc")

    def test_orders_blocked_even_when_disconnected(self, broker: PaperBroker) -> None:
        # Safety gate must not depend on connection state.
        with pytest.raises(LiveTradingDisabledError):
            broker.place_order(tradingsymbol="RELIANCE")

    def test_paper_broker_is_not_zerodha_broker(self) -> None:
        # Sanity check: PaperBroker is its own concrete class.
        from trading_engine.broker.zerodha.client import ZerodhaBroker
        assert not isinstance(PaperBroker(), ZerodhaBroker)
