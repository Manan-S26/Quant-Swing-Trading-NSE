"""Tests for SlippageModel."""

from __future__ import annotations

from decimal import Decimal

import pytest

from trading_engine.backtest.slippage_model import SlippageModel


class TestSlippageModelBuy:
    def test_buy_price_increases(self) -> None:
        model = SlippageModel(bps=Decimal("2"))
        adjusted = model.apply("BUY", Decimal("1000"))
        assert adjusted > Decimal("1000")

    def test_buy_price_increase_amount(self) -> None:
        model = SlippageModel(bps=Decimal("10"))
        adjusted = model.apply("BUY", Decimal("1000"))
        # 10 bps = 0.1% of 1000 = 1.00
        assert adjusted == Decimal("1001.00")

    def test_buy_returns_decimal(self) -> None:
        model = SlippageModel()
        result = model.apply("BUY", Decimal("500"))
        assert isinstance(result, Decimal)


class TestSlippageModelSell:
    def test_sell_price_decreases(self) -> None:
        model = SlippageModel(bps=Decimal("2"))
        adjusted = model.apply("SELL", Decimal("1000"))
        assert adjusted < Decimal("1000")

    def test_sell_price_decrease_amount(self) -> None:
        model = SlippageModel(bps=Decimal("10"))
        adjusted = model.apply("SELL", Decimal("1000"))
        # 10 bps = 0.1% of 1000 = 1.00
        assert adjusted == Decimal("999.00")

    def test_sell_returns_decimal(self) -> None:
        model = SlippageModel()
        result = model.apply("SELL", Decimal("500"))
        assert isinstance(result, Decimal)


class TestSlippageModelZeroBps:
    def test_zero_bps_buy_unchanged(self) -> None:
        model = SlippageModel(bps=Decimal("0"))
        adjusted = model.apply("BUY", Decimal("1000"))
        assert adjusted == Decimal("1000.00")

    def test_zero_bps_sell_unchanged(self) -> None:
        model = SlippageModel(bps=Decimal("0"))
        adjusted = model.apply("SELL", Decimal("1000"))
        assert adjusted == Decimal("1000.00")


class TestSlippageModelValidation:
    def test_negative_bps_raises(self) -> None:
        with pytest.raises(ValueError, match="bps"):
            SlippageModel(bps=Decimal("-1"))

    def test_zero_price_raises(self) -> None:
        model = SlippageModel()
        with pytest.raises(ValueError, match="price"):
            model.apply("BUY", Decimal("0"))

    def test_negative_price_raises(self) -> None:
        model = SlippageModel()
        with pytest.raises(ValueError, match="price"):
            model.apply("SELL", Decimal("-100"))

    def test_invalid_side_raises(self) -> None:
        model = SlippageModel()
        with pytest.raises(ValueError, match="side"):
            model.apply("HOLD", Decimal("100"))
