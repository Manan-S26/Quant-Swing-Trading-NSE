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


# ---------------------------------------------------------------------------
# Milestone 13 — new metric fields
# ---------------------------------------------------------------------------


class TestAverageAndBestWorstTrade:
    def test_average_trade_pnl(self) -> None:
        # BUY 10 @ 500, SELL 10 @ 600 → pnl=1000
        # BUY 10 @ 500, SELL 10 @ 450 → pnl=-500
        # average = (1000 + -500) / 2 = 250
        fills = [
            _fill(Side.BUY, 10, _D("500")),
            _fill(Side.SELL, 10, _D("600")),
            _fill(Side.BUY, 10, _D("500")),
            _fill(Side.SELL, 10, _D("450")),
        ]
        m = calculate_backtest_metrics(_D("100000"), _D("100500"), [], fills)
        assert m.average_trade_pnl == _D("250")

    def test_best_trade_pnl(self) -> None:
        fills = [
            _fill(Side.BUY, 10, _D("500")),
            _fill(Side.SELL, 10, _D("600")),  # +1000
            _fill(Side.BUY, 10, _D("500")),
            _fill(Side.SELL, 10, _D("450")),  # -500
        ]
        m = calculate_backtest_metrics(_D("100000"), _D("100500"), [], fills)
        assert m.best_trade_pnl == _D("1000")

    def test_worst_trade_pnl(self) -> None:
        fills = [
            _fill(Side.BUY, 10, _D("500")),
            _fill(Side.SELL, 10, _D("600")),  # +1000
            _fill(Side.BUY, 10, _D("500")),
            _fill(Side.SELL, 10, _D("450")),  # -500
        ]
        m = calculate_backtest_metrics(_D("100000"), _D("100500"), [], fills)
        assert m.worst_trade_pnl == _D("-500")

    def test_no_trades_average_is_zero(self) -> None:
        m = calculate_backtest_metrics(_D("100000"), _D("100000"), [], [])
        assert m.average_trade_pnl == _D("0")
        assert m.best_trade_pnl == _D("0")
        assert m.worst_trade_pnl == _D("0")


class TestSharpeRatio:
    def test_flat_equity_returns_none(self) -> None:
        # All returns are zero — std_dev=0, Sharpe undefined
        curve = _curve(100000, 100000, 100000, 100000)
        m = calculate_backtest_metrics(_D("100000"), _D("100000"), curve, [])
        assert m.sharpe_ratio is None

    def test_single_point_returns_none(self) -> None:
        curve = [(datetime(2024, 1, 15, 9, 15), _D("100000"))]
        m = calculate_backtest_metrics(_D("100000"), _D("100000"), curve, [])
        assert m.sharpe_ratio is None

    def test_volatile_equity_returns_float(self) -> None:
        # Alternating up/down equity gives a non-trivial Sharpe
        curve = _curve(100000, 110000, 105000, 115000, 112000)
        m = calculate_backtest_metrics(_D("100000"), _D("112000"), curve, [])
        assert m.sharpe_ratio is not None
        assert isinstance(m.sharpe_ratio, float)

    def test_empty_equity_curve_returns_none(self) -> None:
        m = calculate_backtest_metrics(_D("100000"), _D("100000"), [], [])
        assert m.sharpe_ratio is None


class TestSortinoRatio:
    def test_no_losses_returns_none(self) -> None:
        # Monotonically increasing equity — no downside returns
        curve = _curve(100000, 101000, 102000, 103000)
        m = calculate_backtest_metrics(_D("100000"), _D("103000"), curve, [])
        assert m.sortino_ratio is None  # undefined (infinite)

    def test_with_losses_returns_float(self) -> None:
        curve = _curve(100000, 110000, 95000, 108000, 100000)
        m = calculate_backtest_metrics(_D("100000"), _D("100000"), curve, [])
        assert m.sortino_ratio is not None


class TestCAGR:
    def test_cagr_none_without_timestamps(self) -> None:
        m = calculate_backtest_metrics(_D("100000"), _D("110000"), [], [])
        assert m.cagr is None

    def test_cagr_none_for_too_short_period(self) -> None:
        start = datetime(2024, 1, 15, 9, 15)
        end = datetime(2024, 1, 15, 9, 16)  # 1 minute
        m = calculate_backtest_metrics(
            _D("100000"), _D("110000"), [], [], start_time=start, end_time=end
        )
        assert m.cagr is None

    def test_cagr_returns_float_for_full_year(self) -> None:
        start = datetime(2023, 1, 1)
        end = datetime(2024, 1, 1)
        m = calculate_backtest_metrics(
            _D("100000"), _D("110000"), [], [], start_time=start, end_time=end
        )
        assert m.cagr is not None
        assert isinstance(m.cagr, float)
        assert abs(m.cagr - 0.10) < 0.01  # ≈ 10%

    def test_cagr_none_for_zero_initial_cash(self) -> None:
        start = datetime(2023, 1, 1)
        end = datetime(2024, 1, 1)
        m = calculate_backtest_metrics(
            _D("0"), _D("110000"), [], [], start_time=start, end_time=end
        )
        assert m.cagr is None
