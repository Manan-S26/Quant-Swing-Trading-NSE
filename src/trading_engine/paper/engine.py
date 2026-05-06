"""Paper trading engine — the main event loop for paper mode.

Iterates PaperMarketFeed bars, routes them to the strategy, applies the
risk engine, passes approved intents to PaperExecutionBroker, and returns a
PaperTradingReport.

No Zerodha imports. No real orders. No credentials required.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from trading_engine.domain.models import RiskDecision, TradeFill
from trading_engine.paper.broker import PaperExecutionBroker
from trading_engine.paper.market_feed import PaperMarketFeed
from trading_engine.paper.portfolio import PaperPortfolio
from trading_engine.paper.report import PaperTradingReport
from trading_engine.risk.engine import RiskEngine
from trading_engine.strategy.base import Strategy, StrategyContext
from trading_engine.strategy.signals import OrderIntent


class PaperTradingEngine:
    """Runs a strategy against a PaperMarketFeed and returns a PaperTradingReport.

    Mirrors BacktestEngine in structure but uses paper-trading components and
    produces a PaperTradingReport (no metrics — paper mode is forward-only).

    Args:
        strategy:          Strategy instance to run.
        market_feed:       PaperMarketFeed providing bars in order.
        portfolio:         PaperPortfolio tracking cash and positions.
        execution_broker:  PaperExecutionBroker that simulates fills.
        risk_engine:       Optional RiskEngine. None = all intents approved.
        strategy_id:       Identifier embedded in PaperTradingReport.
        symbols:           Symbols being traded (embedded in the report).
        initial_cash:      Starting cash (for the report header).
        parameters:        Arbitrary metadata recorded in the report.
        logger:            Optional logger override.
    """

    def __init__(
        self,
        strategy: Strategy,
        market_feed: PaperMarketFeed,
        portfolio: PaperPortfolio,
        execution_broker: PaperExecutionBroker,
        strategy_id: str,
        symbols: list[str],
        initial_cash: Decimal,
        risk_engine: RiskEngine | None = None,
        parameters: dict[str, Any] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._strategy = strategy
        self._feed = market_feed
        self._portfolio = portfolio
        self._broker = execution_broker
        self._risk_engine = risk_engine
        self._strategy_id = strategy_id
        self._symbols = symbols
        self._initial_cash = initial_cash
        self._parameters = parameters or {}
        self._logger = logger or logging.getLogger(__name__)

    def run(self) -> PaperTradingReport:
        """Execute the paper trading run and return the full report.

        Execution flow per bar:
          1. Call strategy.on_bar() to get OrderIntents.
          2. Run each intent through the RiskEngine (if provided).
          3. Pass approved intents to PaperExecutionBroker.
          4. Mark portfolio to market.
          5. Record equity and any fills.
        """
        context = StrategyContext(
            strategy_id=self._strategy_id,
            mode="paper",
            config=self._parameters,
        )
        self._strategy.on_start(context)

        fills: list[TradeFill] = []
        rejected_decisions: list[RiskDecision] = []
        start_time: datetime | None = None
        end_time: datetime | None = None
        latest_prices: dict[str, Decimal] = {}

        self._logger.info(
            "Paper trading starting — strategy=%s symbols=%s",
            self._strategy_id,
            self._symbols,
        )

        for ts, symbol, bar in self._feed.iter_bars():
            if start_time is None:
                start_time = ts
            end_time = ts
            latest_prices[symbol] = bar.close

            order_intents: list[OrderIntent] = self._strategy.on_bar(bar, context)

            for intent in order_intents:
                decision = self._run_risk_check(intent, ts)
                if decision is not None and not decision.approved:
                    rejected_decisions.append(decision)
                    self._logger.warning(
                        "Risk rejected %s %s %s: %s",
                        intent.side,
                        intent.symbol,
                        intent.order_type,
                        decision.reason_code,
                    )
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

            self._portfolio.mark_to_market(ts, latest_prices)

        self._strategy.on_stop(context)

        final_equity = self._portfolio.total_equity(latest_prices)

        self._logger.info(
            "Paper trading complete — fills=%d final_equity=%s",
            len(fills),
            str(final_equity),
        )

        return PaperTradingReport(
            strategy_id=self._strategy_id,
            symbols=self._symbols,
            start_time=start_time,
            end_time=end_time,
            initial_cash=self._initial_cash,
            final_equity=final_equity,
            fills=fills,
            rejected_risk_decisions=rejected_decisions,
            equity_curve=self._portfolio.equity_curve,
            parameters=self._parameters,
        )

    # ------------------------------------------------------------------
    # Risk check seam
    # ------------------------------------------------------------------

    def _run_risk_check(
        self,
        intent: OrderIntent,
        ts: datetime,
    ) -> RiskDecision | None:
        """Run intent through RiskEngine if configured; return None to approve.

        Returns:
            None if no risk engine is configured (all intents approved).
            RiskDecision (approved or rejected) when a risk engine is present.
        """
        if self._risk_engine is None:
            return None
        snapshot = self._portfolio.get_snapshot(ts)
        return self._risk_engine.check_order_intent(intent, snapshot, ts)
