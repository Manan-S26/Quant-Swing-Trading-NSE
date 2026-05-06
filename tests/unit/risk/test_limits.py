"""Tests for RiskLimits dataclass."""

from __future__ import annotations

from decimal import Decimal

import pytest

from trading_engine.domain.enums import OrderType, ProductType
from trading_engine.risk.limits import RiskLimits


def test_defaults_are_valid():
    limits = RiskLimits()
    assert limits.max_daily_loss == Decimal("10000")
    assert limits.max_order_value == Decimal("500000")
    assert limits.max_open_positions == 10
    assert limits.max_trades_per_day == 100
    assert limits.max_orders_per_second == 5
    assert limits.allowed_symbols is None
    assert limits.allowed_product_types is None
    assert limits.allowed_order_types is None


def test_custom_values():
    limits = RiskLimits(
        max_daily_loss=Decimal("2000"),
        max_order_value=Decimal("50000"),
        max_open_positions=5,
        max_trades_per_day=20,
        max_orders_per_second=2,
        allowed_symbols={"RELIANCE", "TCS"},
        allowed_product_types={ProductType.MIS},
        allowed_order_types={OrderType.MARKET, OrderType.LIMIT},
    )
    assert limits.max_daily_loss == Decimal("2000")
    assert limits.max_open_positions == 5
    assert "RELIANCE" in limits.allowed_symbols
    assert ProductType.MIS in limits.allowed_product_types


@pytest.mark.parametrize(
    "field, value",
    [
        ("max_daily_loss", Decimal("0")),
        ("max_daily_loss", Decimal("-1")),
        ("max_order_value", Decimal("0")),
        ("max_order_value", Decimal("-500")),
        ("max_open_positions", 0),
        ("max_open_positions", -1),
        ("max_trades_per_day", 0),
        ("max_trades_per_day", -5),
        ("max_orders_per_second", 0),
        ("max_orders_per_second", -1),
    ],
)
def test_invalid_values_raise(field, value):
    kwargs = {field: value}
    with pytest.raises(ValueError):
        RiskLimits(**kwargs)
