"""Paper trading portfolio.

PaperPortfolio is a thin subclass of BacktestPortfolio. In v1 the behaviour is
identical; the subclass exists so paper-mode code imports from the paper package
(clear intent) and can be extended independently of the backtester in later
milestones.

No Zerodha imports. No real broker calls.
"""

from __future__ import annotations

from trading_engine.backtest.portfolio import BacktestPortfolio


class PaperPortfolio(BacktestPortfolio):
    """Portfolio tracker for paper trading.

    Identical to BacktestPortfolio in v1. Tracks cash, positions, fills,
    realized/unrealized P&L, and the equity curve. Long-only.

    Reuses BacktestPortfolio so there is no logic duplication. The subclass
    provides a paper-mode import path and a clean extension point.
    """
