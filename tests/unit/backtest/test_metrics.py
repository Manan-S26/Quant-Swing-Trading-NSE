"""Tests for calculate_backtest_metrics."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trading_engine.backtest.metrics import BacktestMetrics, calculate_backtest_metrics
from trading_engine.domain.enums import Exchange, Side
from trading_engine.domain.models import TradeFill

_D = Decimal


_ZERO_FEES = Decimal("0")


def _fill(side: Side, qty: int, price: Decimal, fees: Decimal = _ZERO_FEES) -> TradeFill:
    return TradeFill(
        fill_id="fill_x",
        internal_order_id="ord_x",
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        side=side,
        quantity=qty,
        price=price,
        fees=fees,
        timestamp=datetime(2024, 1, 15, 9, 15),
    )


def _curve(*equities: float) -> list[tuple[datetime, Decimal]]:
    return [(datetime(2024, 1, 15, 9, 15 + i), Decimal(str(e))) for i, e in enumerate(equities)]


class TestNoTrades:
    def test_no_trades_returns_metrics(self) -> None:
        m = calculate_backtest_metrics(
            initial_cash=_D("100000"),
            final_equity=_D("100000"),
            equity_curve=[],
            fills=[],
        )
        assert isinstance(m, BacktestMetrics)

    def test_no_trades_zero_trade_count(self) -> None:
        m = calculate_backtest_metrics(_D("100000"), _D("100000"), [], [])
        assert m.trade_count == 0

    def test_no_trades_zero_pnl(self) -> None:
        m = calculate_backtest_metrics(_D("100000"), _D("100000"), [], [])
        assert m.total_pnl == _D("0")

    def test_no_trades_zero_win_rate(self) -> None:
        m = calculate_backtest_metrics(_D("100000"), _D("100000"), [], [])
        assert m.win_rate == _D("0")

    def test_no_trades_zero_profit_factor(self) -> None:
        m = calculate_backtest_metrics(_D("100000"), _D("100000"), [], [])
        assert m.profit_factor == _D("0")


class TestProfitableTrade:
    def test_profitable_trade_positive_pnl(self) -> None:
        fills = [
            _fill(Side.BUY, 10, _D("500")),
            _fill(Side.SELL, 10, _D("600")),
        ]
        # final_equity = initial + pnl = 100000 + 1000 = 101000
        m = calculate_backtest_metrics(_D("100000"), _D("101000"), _curve(100000, 101000), fills)
        assert m.total_pnl == _D("1000")
        assert m.total_return > _D("0")

    def test_profitable_trade_positive_realized_pnl(self) -> None:
        fills = [
            _fill(Side.BUY, 10, _D("500")),
            _fill(Side.SELL, 10, _D("600")),
        ]
        m = calculate_backtest_metrics(_D("100000"), _D("101000"), _curve(100000, 101000), fills)
        assert m.realized_pnl == _D("1000")

    def test_profitable_trade_win_rate_100(self) -> None:
        fills = [
            _fill(Side.BUY, 10, _D("500")),
            _fill(Side.SELL, 10, _D("600")),
        ]
        m = calculate_backtest_metrics(_D("100000"), _D("101000"), [], fills)
        assert m.win_rate == _D("1")
        assert m.winning_trades == 1
        assert m.losing_trades == 0

    def test_total_fees_summed(self) -> None:
        fills = [
            _fill(Side.BUY, 10, _D("500"), fees=_D("20")),
            _fill(Side.SELL, 10, _D("600"), fees=_D("25")),
        ]
        m = calculate_backtest_metrics(_D("100000"), _D("101000"), [], fills)
        assert m.total_fees == _D("45")


class TestLosingTrade:
    def test_losing_trade_negative_pnl(self) -> None:
        fills = [
            _fill(Side.BUY, 10, _D("600")),
            _fill(Side.SELL, 10, _D("500")),
        ]
        m = calculate_backtest_metrics(_D("100000"), _D("99000"), [], fills)
        assert m.realized_pnl == _D("-1000")

    def test_losing_trade_zero_win_rate(self) -> None:
        fills = [
            _fill(Side.BUY, 10, _D("600")),
            _fill(Side.SELL, 10, _D("500")),
        ]
        m = calculate_backtest_metrics(_D("100000"), _D("99000"), [], fills)
        assert m.win_rate == _D("0")
        assert m.losing_trades == 1


class TestMaxDrawdown:
    def test_flat_equity_zero_drawdown(self) -> None:
        m = calculate_backtest_metrics(
            _D("100000"),
            _D("100000"),
            _curve(100000, 100000, 100000),
            [],
        )
        assert m.max_drawdown == _D("0")

    def test_drawdown_calculated_correctly(self) -> None:
        # Peak=110000, trough=99000 → dd=(110000-99000)/110000 ≈ 0.1
        m = calculate_backtest_metrics(
            _D("100000"),
            _D("105000"),
            _curve(100000, 110000, 99000, 105000),
            [],
        )
        expected = (Decimal("110000") - Decimal("99000")) / Decimal("110000")
        assert abs(m.max_drawdown - expected) < Decimal("0.001")

    def test_no_equity_curve_zero_drawdown(self) -> None:
        m = calculate_backtest_metrics(_D("100000"), _D("100000"), [], [])
        assert m.max_drawdown == _D("0")


class TestProfitFactor:
    def test_profit_factor_with_mixed_trades(self) -> None:
        fills = [
            _fill(Side.BUY, 10, _D("500")),
            _fill(Side.SELL, 10, _D("600")),  # +1000
            _fill(Side.BUY, 10, _D("500")),
            _fill(Side.SELL, 10, _D("450")),  # -500
        ]
        m = calculate_backtest_metrics(_D("100000"), _D("100500"), [], fills)
        # gross profit=1000, gross loss=500 → pf=2
        assert m.profit_factor == _D("2")
