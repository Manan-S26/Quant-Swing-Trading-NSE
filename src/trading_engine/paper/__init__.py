"""Paper trading engine package.

Implements paper trading with synthetic execution: no Zerodha API calls,
no real orders, no credentials required. Safe to run in tests and local dev.

Difference from backtesting:
- Intended for forward simulation against live (or simulated live) bar feeds.
- Uses PaperMarketFeed instead of HistoricalDataFeed.
- Uses PaperPortfolio, PaperExecutionBroker, and PaperTradingEngine.
- Produces PaperTradingReport (no strategy metrics — forward mode only).

Relationship to broker/paper.py:
- broker/paper.py is the Broker-interface stub (connection lifecycle, no orders).
- paper/broker.py is the execution simulator (fills orders against synthetic bars).
"""
