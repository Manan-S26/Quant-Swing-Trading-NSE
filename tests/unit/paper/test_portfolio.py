"""Tests for PaperPortfolio."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from trading_engine.backtest.portfolio import InsufficientPositionError
from trading_engine.domain.enums import Exchange, Side
from trading_engine.domain.identifiers import generate_fill_id, generate_internal_order_id
from trading_engine.domain.models import TradeFill
from trading_engine.paper.portfolio import PaperPortfolio

_TS = datetime(2024, 1, 15, 9, 30)


def _make_fill(
    *,
    symbol: str = "RELIANCE",
    side: Side = Side.BUY,
    quantity: int = 10,
    price: Decimal = Decimal("100"),
    fees: Decimal = Decimal("0"),
    ts: datetime = _TS,
) -> TradeFill:
    return TradeFill(
        fill_id=generate_fill_id(),
        internal_order_id=generate_internal_order_id(),
        symbol=symbol,
        exchange=Exchange.NSE,
        side=side,
        quantity=quantity,
        price=price,
        fees=fees,
        timestamp=ts,
    )


class TestBuyCreatesPosition:
    def test_buy_creates_position(self):
        portfolio = PaperPortfolio(initial_cash=Decimal("100000"))
        fill = _make_fill(quantity=10, price=Decimal("100"))
        portfolio.apply_fill(fill)
        pos = portfolio.get_position("RELIANCE")
        assert pos is not None
        assert pos.quantity == 10
        assert pos.average_price == Decimal("100")

    def test_buy_reduces_cash(self):
        portfolio = PaperPortfolio(initial_cash=Decimal("100000"))
        fill = _make_fill(quantity=10, price=Decimal("100"), fees=Decimal("20"))
        portfolio.apply_fill(fill)
        # cash = 100000 - (10 * 100) - 20 = 98980
        assert portfolio.cash == Decimal("98980")

    def test_buy_average_price_weighted(self):
        portfolio = PaperPortfolio(initial_cash=Decimal("100000"))
        portfolio.apply_fill(_make_fill(quantity=10, price=Decimal("100")))
        portfolio.apply_fill(_make_fill(quantity=10, price=Decimal("200")))
        pos = portfolio.get_position("RELIANCE")
        # avg = (10*100 + 10*200) / 20 = 150
        assert pos.average_price == Decimal("150")
        assert pos.quantity == 20


class TestSellReducesPosition:
    def test_sell_reduces_position(self):
        portfolio = PaperPortfolio(initial_cash=Decimal("100000"))
        portfolio.apply_fill(_make_fill(quantity=10, price=Decimal("100")))
        portfolio.apply_fill(_make_fill(side=Side.SELL, quantity=5, price=Decimal("110")))
        pos = portfolio.get_position("RELIANCE")
        assert pos.quantity == 5

    def test_sell_increases_cash(self):
        portfolio = PaperPortfolio(initial_cash=Decimal("100000"))
        portfolio.apply_fill(_make_fill(quantity=10, price=Decimal("100")))
        cash_before_sell = portfolio.cash
        portfolio.apply_fill(
            _make_fill(side=Side.SELL, quantity=10, price=Decimal("110"), fees=Decimal("20"))
        )
        # cash increases by (10 * 110) - 20 = 1080
        assert portfolio.cash == cash_before_sell + Decimal("1080")

    def test_cannot_sell_more_than_owned(self):
        portfolio = PaperPortfolio(initial_cash=Decimal("100000"))
        portfolio.apply_fill(_make_fill(quantity=5, price=Decimal("100")))
        with pytest.raises(InsufficientPositionError):
            portfolio.apply_fill(_make_fill(side=Side.SELL, quantity=10, price=Decimal("100")))


class TestMarkToMarket:
    def test_mark_to_market_updates_unrealized_pnl(self):
        portfolio = PaperPortfolio(initial_cash=Decimal("100000"))
        portfolio.apply_fill(_make_fill(quantity=10, price=Decimal("100")))
        ts = datetime(2024, 1, 15, 9, 31)
        portfolio.mark_to_market(ts, {"RELIANCE": Decimal("110")})
        pos = portfolio.get_position("RELIANCE")
        # unrealized = 10 * (110 - 100) = 100
        assert pos.unrealized_pnl == Decimal("100")

    def test_mark_to_market_records_equity_curve_point(self):
        portfolio = PaperPortfolio(initial_cash=Decimal("100000"))
        ts = datetime(2024, 1, 15, 9, 31)
        portfolio.mark_to_market(ts, {})
        assert len(portfolio.equity_curve) == 1
        assert portfolio.equity_curve[0][0] == ts


class TestSnapshot:
    def test_snapshot_compatible_with_risk_engine(self):
        from trading_engine.risk.engine import RiskEngine
        from trading_engine.risk.limits import RiskLimits

        portfolio = PaperPortfolio(initial_cash=Decimal("100000"))
        portfolio.apply_fill(_make_fill(quantity=5, price=Decimal("100")))
        snapshot = portfolio.get_snapshot(_TS)

        engine = RiskEngine(limits=RiskLimits(max_order_value=Decimal("50000")))
        from trading_engine.strategy.signals import OrderIntent

        intent = OrderIntent(
            strategy_id="test",
            symbol="RELIANCE",
            exchange="NSE",
            side="BUY",
            quantity=1,
            order_type="MARKET",
            product="MIS",
            price=Decimal("100"),
        )
        decision = engine.check_order_intent(intent, snapshot, _TS)
        assert decision.approved

    def test_snapshot_has_correct_fields(self):
        portfolio = PaperPortfolio(initial_cash=Decimal("50000"))
        snapshot = portfolio.get_snapshot(_TS)
        assert snapshot.cash == Decimal("50000")
        assert snapshot.timestamp == _TS
        assert snapshot.positions == []


class TestPaperPortfolioIsSubclass:
    def test_is_subclass_of_backtest_portfolio(self):
        from trading_engine.backtest.portfolio import BacktestPortfolio

        portfolio = PaperPortfolio(initial_cash=Decimal("10000"))
        assert isinstance(portfolio, BacktestPortfolio)
