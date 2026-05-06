"""Tests for CostModel."""

from __future__ import annotations

from decimal import Decimal

import pytest

from trading_engine.backtest.cost_model import CostModel


class TestCostModelDefaults:
    def test_buy_fees_positive(self) -> None:
        model = CostModel()
        fees = model.calculate_fees("BUY", 100, Decimal("500"))
        assert fees > 0

    def test_sell_fees_positive(self) -> None:
        model = CostModel()
        fees = model.calculate_fees("SELL", 100, Decimal("500"))
        assert fees > 0

    def test_fees_are_decimal(self) -> None:
        model = CostModel()
        fees = model.calculate_fees("BUY", 50, Decimal("1000"))
        assert isinstance(fees, Decimal)

    def test_fees_not_negative(self) -> None:
        model = CostModel()
        fees = model.calculate_fees("BUY", 1, Decimal("10"))
        assert fees >= 0

    def test_sell_fees_include_stt(self) -> None:
        # SELL should have higher fees than BUY due to STT on sell side.
        model = CostModel()
        buy_fees = model.calculate_fees("BUY", 100, Decimal("500"))
        sell_fees = model.calculate_fees("SELL", 100, Decimal("500"))
        assert sell_fees > buy_fees

    def test_larger_trade_higher_fees(self) -> None:
        model = CostModel()
        small = model.calculate_fees("BUY", 10, Decimal("100"))
        large = model.calculate_fees("BUY", 1000, Decimal("100"))
        assert large > small


class TestCostModelValidation:
    def test_zero_quantity_raises(self) -> None:
        model = CostModel()
        with pytest.raises(ValueError, match="quantity"):
            model.calculate_fees("BUY", 0, Decimal("100"))

    def test_negative_quantity_raises(self) -> None:
        model = CostModel()
        with pytest.raises(ValueError, match="quantity"):
            model.calculate_fees("BUY", -1, Decimal("100"))

    def test_zero_price_raises(self) -> None:
        model = CostModel()
        with pytest.raises(ValueError, match="price"):
            model.calculate_fees("BUY", 10, Decimal("0"))

    def test_negative_price_raises(self) -> None:
        model = CostModel()
        with pytest.raises(ValueError, match="price"):
            model.calculate_fees("BUY", 10, Decimal("-100"))

    def test_invalid_side_raises(self) -> None:
        model = CostModel()
        with pytest.raises(ValueError, match="side"):
            model.calculate_fees("HOLD", 10, Decimal("100"))

    def test_negative_brokerage_raises(self) -> None:
        with pytest.raises(ValueError):
            CostModel(brokerage_per_order=Decimal("-1"))

    def test_negative_rate_raises(self) -> None:
        with pytest.raises(ValueError):
            CostModel(stt_rate=Decimal("-0.001"))


class TestCostModelZeroFees:
    def test_zero_brokerage_zero_rates_gives_stamp_duty_only_on_buy(self) -> None:
        model = CostModel(
            brokerage_per_order=Decimal("0"),
            brokerage_cap=Decimal("0"),
            stt_rate=Decimal("0"),
            exchange_txn_rate=Decimal("0"),
            sebi_rate=Decimal("0"),
            stamp_duty_rate=Decimal("0.001"),
            gst_rate=Decimal("0"),
        )
        fees = model.calculate_fees("BUY", 100, Decimal("100"))
        assert fees == Decimal("10.00")  # 100 * 100 * 0.001 = 10
