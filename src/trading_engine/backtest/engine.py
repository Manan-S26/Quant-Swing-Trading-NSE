"""Backtest engine — the main event loop.

Iterates historical bars, routes them to the strategy, passes order intents
to the simulated broker, tracks fills and equity, and returns a BacktestReport.

No live broker usage. No Zerodha calls. No real order placement.

Risk check seam: see _risk_check() — currently a pass-through placeholder
that can be wired to a real risk engine in a later milestone.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from trading_engine.backtest.data_feed import HistoricalDataFeed
from trading_engine.backtest.metrics import calculate_backtest_metrics
from trading_engine.backtest.portfolio import BacktestPortfolio
from trading_engine.backtest.report import BacktestReport
from trading_engine.backtest.simulated_broker import SimulatedBroker
from trading_engine.domain.models import TradeFill
from trading_engine.strategy.base import Strategy, StrategyContext
from trading_engine.strategy.signals import OrderIntent

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Runs a strategy against historical data and returns a BacktestReport.

    Args:
        strategy:          Strategy instance to run.
        data_feed:         HistoricalDataFeed providing bars in order.
        portfolio:         BacktestPortfolio tracking cash and positions.
        simulated_broker:  SimulatedBroker that executes order intents.
        initial_cash:      Starting cash (used for metrics calculation).
        strategy_id:       Identifier embedded in the BacktestReport.
        symbols:           Symbols being traded (embedded in the report).
        parameters:        Arbitrary metadata recorded in the report.
        logger:            Optional logger override.
    """

    def __init__(
        self,
        strategy: Strategy,
        data_feed: HistoricalDataFeed,
        portfolio: BacktestPortfolio,
        simulated_broker: SimulatedBroker,
        initial_cash: Decimal,
        strategy_id: str,
        symbols: list[str],
        parameters: dict[str, Any] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._strategy = strategy
        self._data_feed = data_feed
        self._portfolio = portfolio
        self._broker = simulated_broker
        self._initial_cash = initial_cash
        self._strategy_id = strategy_id
        self._symbols = symbols
        self._parameters = parameters or {}
        self._logger = logger or logging.getLogger(__name__)

    def run(self) -> BacktestReport:
        """Execute the backtest and return the full report.

        Execution flow per bar:
          1. Emit MarketDataEvent (internal).
          2. Call strategy.on_bar() to get OrderIntents.
          3. Run each intent through _risk_check() (placeholder).
          4. Pass approved intents to SimulatedBroker.
          5. Mark portfolio to market.
          6. Record equity and any fills.
        """
        context = StrategyContext(
            strategy_id=self._strategy_id,
            mode="backtest",
            config=self._parameters,
        )
        self._strategy.on_start(context)

        fills: list[TradeFill] = []
        start_time: datetime | None = None
        end_time: datetime | None = None
        latest_prices: dict[str, Decimal] = {}

        self._logger.info(
            "Backtest starting — strategy=%s symbols=%s",
            self._strategy_id,
            self._symbols,
        )

        for ts, symbol, bar in self._data_feed.iter_bars():
            if start_time is None:
                start_time = ts
            end_time = ts
            latest_prices[symbol] = bar.close

            # Strategy signal.
            order_intents: list[OrderIntent] = self._strategy.on_bar(bar, context)

            for intent in order_intents:
                # Risk check seam — always passes in v1.
                if not self._risk_check(intent):
                    self._logger.warning("Risk check rejected intent: %s", intent)
                    continue

                try:
                    fill = self._broker.execute_order_intent(intent, bar)
                except Exception as exc:
                    self._logger.warning(
                        "Order execution error for %s %s: %s",
                        intent.side,
                        intent.symbol,
                        exc,
                    )
                    fill = None

                if fill is not None:
                    fills.append(fill)

            # Mark portfolio to market after each bar.
            self._portfolio.mark_to_market(ts, latest_prices)

        self._strategy.on_stop(context)

        final_equity = self._portfolio.total_equity(latest_prices)
        metrics = calculate_backtest_metrics(
            initial_cash=self._initial_cash,
            final_equity=final_equity,
            equity_curve=self._portfolio.equity_curve,
            fills=fills,
        )

        self._logger.info(
            "Backtest complete — fills=%d final_equity=%s total_return=%s",
            len(fills),
            str(final_equity),
            str(metrics.total_return),
        )

        return BacktestReport(
            strategy_id=self._strategy_id,
            symbols=self._symbols,
            start_time=start_time,
            end_time=end_time,
            initial_cash=self._initial_cash,
            final_equity=final_equity,
            metrics=metrics,
            fills=fills,
            equity_curve=self._portfolio.equity_curve,
            parameters=self._parameters,
        )

    # ------------------------------------------------------------------
    # Risk check seam (Milestone 7 will wire the real risk engine here)
    # ------------------------------------------------------------------

    def _risk_check(self, intent: OrderIntent) -> bool:
        """Placeholder risk gate. Always approves in backtest v1.

        In Milestone 7, this method will be replaced by a call to a
        RiskEngine that enforces daily loss limits, position limits, etc.
        """
        return True
