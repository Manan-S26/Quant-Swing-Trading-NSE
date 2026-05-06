"""Canonical enumerations for the trading engine.

All modules that need to express Side, OrderType, OrderStatus, etc. should
import from here rather than using raw strings, so that typos are caught at
definition time rather than at runtime.

StrEnum members compare equal to their string values, which makes them safe
to use in dict lookups and API payloads without extra conversion.

Note on OrderType.SL_M:
    The enum member is named SL_M (Python-safe identifier) but its string
    value is "SL-M" to match the Zerodha API and the existing signals.py
    validation set.
"""

from __future__ import annotations

from enum import StrEnum


class TradingMode(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"  # Value matches Zerodha API format


class ProductType(StrEnum):
    MIS = "MIS"  # Margin Intraday Square-off
    CNC = "CNC"  # Cash-and-Carry (delivery)
    NRML = "NRML"  # Normal (F&O, not used in v1)


class TimeInForce(StrEnum):
    DAY = "DAY"
    IOC = "IOC"


class OrderStatus(StrEnum):
    CREATED = "CREATED"
    RISK_APPROVED = "RISK_APPROVED"
    RISK_REJECTED = "RISK_REJECTED"
    SUBMITTED = "SUBMITTED"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    RECONCILED = "RECONCILED"


class SignalType(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    MODIFY = "MODIFY"
    CANCEL = "CANCEL"
    HOLD = "HOLD"


class RiskReasonCode(StrEnum):
    APPROVED = "APPROVED"
    LIVE_TRADING_DISABLED = "LIVE_TRADING_DISABLED"
    DAILY_LOSS_LIMIT_BREACHED = "DAILY_LOSS_LIMIT_BREACHED"
    ORDER_VALUE_LIMIT_BREACHED = "ORDER_VALUE_LIMIT_BREACHED"
    POSITION_LIMIT_BREACHED = "POSITION_LIMIT_BREACHED"
    SYMBOL_NOT_ALLOWED = "SYMBOL_NOT_ALLOWED"
    PRODUCT_NOT_ALLOWED = "PRODUCT_NOT_ALLOWED"
    ORDER_TYPE_NOT_ALLOWED = "ORDER_TYPE_NOT_ALLOWED"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    OUTSIDE_TRADING_WINDOW = "OUTSIDE_TRADING_WINDOW"
    RATE_LIMIT_BREACHED = "RATE_LIMIT_BREACHED"
    INVALID_ORDER = "INVALID_ORDER"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    UNKNOWN = "UNKNOWN"
