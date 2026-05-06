"""Tests for domain enumerations."""

from __future__ import annotations

from trading_engine.domain.enums import (
    Exchange,
    OrderStatus,
    OrderType,
    ProductType,
    RiskReasonCode,
    Side,
    SignalType,
    TimeInForce,
    TradingMode,
)


class TestTradingMode:
    def test_members_exist(self) -> None:
        assert TradingMode.BACKTEST
        assert TradingMode.PAPER
        assert TradingMode.LIVE

    def test_string_values(self) -> None:
        assert TradingMode.BACKTEST == "backtest"
        assert TradingMode.PAPER == "paper"
        assert TradingMode.LIVE == "live"

    def test_is_str(self) -> None:
        assert isinstance(TradingMode.LIVE, str)


class TestExchange:
    def test_nse_value(self) -> None:
        assert Exchange.NSE == "NSE"

    def test_bse_value(self) -> None:
        assert Exchange.BSE == "BSE"

    def test_is_str(self) -> None:
        assert isinstance(Exchange.NSE, str)


class TestSide:
    def test_buy_value(self) -> None:
        assert Side.BUY == "BUY"

    def test_sell_value(self) -> None:
        assert Side.SELL == "SELL"

    def test_exactly_two_members(self) -> None:
        assert len(Side) == 2


class TestOrderType:
    def test_market_value(self) -> None:
        assert OrderType.MARKET == "MARKET"

    def test_limit_value(self) -> None:
        assert OrderType.LIMIT == "LIMIT"

    def test_sl_value(self) -> None:
        assert OrderType.SL == "SL"

    def test_sl_m_value_uses_hyphen(self) -> None:
        # String value must match Zerodha API format "SL-M", not "SL_M".
        assert OrderType.SL_M == "SL-M"

    def test_sl_m_usable_in_string_context(self) -> None:
        assert f"order type: {OrderType.SL_M}" == "order type: SL-M"

    def test_exactly_four_members(self) -> None:
        assert len(OrderType) == 4


class TestProductType:
    def test_mis_value(self) -> None:
        assert ProductType.MIS == "MIS"

    def test_cnc_value(self) -> None:
        assert ProductType.CNC == "CNC"

    def test_nrml_value(self) -> None:
        assert ProductType.NRML == "NRML"


class TestTimeInForce:
    def test_day_value(self) -> None:
        assert TimeInForce.DAY == "DAY"

    def test_ioc_value(self) -> None:
        assert TimeInForce.IOC == "IOC"


class TestOrderStatus:
    def test_all_required_statuses_exist(self) -> None:
        required = [
            "CREATED",
            "RISK_APPROVED",
            "RISK_REJECTED",
            "SUBMITTED",
            "OPEN",
            "PARTIALLY_FILLED",
            "FILLED",
            "CANCEL_REQUESTED",
            "CANCELLED",
            "REJECTED",
            "FAILED",
            "UNKNOWN",
            "RECONCILED",
        ]
        values = {s.value for s in OrderStatus}
        for status in required:
            assert status in values, f"{status} missing from OrderStatus"

    def test_terminal_statuses_present(self) -> None:
        terminal = {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED,
        }
        assert terminal.issubset(set(OrderStatus))


class TestSignalType:
    def test_entry_exit_present(self) -> None:
        assert SignalType.ENTRY == "ENTRY"
        assert SignalType.EXIT == "EXIT"

    def test_all_five_members(self) -> None:
        assert len(SignalType) == 5


class TestRiskReasonCode:
    def test_approved_code(self) -> None:
        assert RiskReasonCode.APPROVED == "APPROVED"

    def test_all_rejection_codes_present(self) -> None:
        rejection_codes = [
            "LIVE_TRADING_DISABLED",
            "DAILY_LOSS_LIMIT_BREACHED",
            "ORDER_VALUE_LIMIT_BREACHED",
            "POSITION_LIMIT_BREACHED",
            "SYMBOL_NOT_ALLOWED",
            "PRODUCT_NOT_ALLOWED",
            "ORDER_TYPE_NOT_ALLOWED",
            "MARKET_DATA_STALE",
            "OUTSIDE_TRADING_WINDOW",
            "RATE_LIMIT_BREACHED",
            "INVALID_ORDER",
            "KILL_SWITCH_ACTIVE",
            "UNKNOWN",
        ]
        values = {c.value for c in RiskReasonCode}
        for code in rejection_codes:
            assert code in values, f"{code} missing from RiskReasonCode"

    def test_str_enum_comparable_to_string(self) -> None:
        assert RiskReasonCode.KILL_SWITCH_ACTIVE == "KILL_SWITCH_ACTIVE"
