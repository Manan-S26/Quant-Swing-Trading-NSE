# Personal Trading Engine Spec

## 1. Objective

Build a personal automated stock trading engine that can backtest, paper trade, and eventually place controlled intraday stock trades through Zerodha Kite Connect.

The engine should prioritize reliability, safety, repeatability, and auditability over speed or strategy complexity.

The goal is not to guarantee profits. The goal is to create a disciplined trading software system where strategies can be tested, rejected, paper traded, and only then enabled for small live execution.

## 2. Scope

### In scope for v1

- Indian stocks only
- NSE cash equities first
- Intraday trading only
- Zerodha Kite Connect integration
- Historical candle download and storage
- Live market data subscription
- Strategy interface
- Backtesting engine
- Paper trading engine
- Risk engine
- Order management system
- Streamlit dashboard
- Full logs and audit trail
- Manual kill switch
- Docker-based local and cloud deployment

### Out of scope for v1

- Options
- Futures
- Commodity trading
- Currency trading
- Multi-broker routing
- High-frequency trading
- Machine learning strategies
- Automated options selling
- Portfolio investing
- Delivery-based investing
- Social signal scraping
- News-based automation
- Fully unattended scale-up

## 3. Trading scope

| Area | v1 decision |
|---|---|
| Asset class | Stocks |
| Exchange | NSE first |
| Broker | Zerodha |
| Product | MIS for intraday |
| Order types | LIMIT, MARKET, SL, SL-M |
| Universe | NIFTY 50 or NIFTY 100 subset |
| Trading direction | Long-only first, shorting later |
| Frequency | Low to medium frequency |
| Live scale | Tiny quantity first |

## 4. Supported modes

### Backtest mode

Runs a strategy on historical data without broker connectivity.

Requirements:

- Load historical candles
- Run strategy on historical events
- Simulate orders and fills
- Apply brokerage, taxes, and slippage
- Track positions and P&L
- Generate trade logs and performance reports

### Paper trading mode

Runs a strategy during market hours using live market data, but does not place real orders.

Requirements:

- Connect to live market data
- Generate real signals
- Simulate fills
- Track paper orders, positions, and P&L
- Store daily reports
- Compare paper assumptions against live market movement

### Live trading mode

Places real Zerodha orders only after manual enablement and risk approval.

Requirements:

- Connect to live market data
- Connect to Zerodha order APIs
- Generate order intents
- Run risk checks
- Place approved orders
- Track order states
- Reconcile broker positions
- Stop automatically on critical failures

## 5. Trading universe

Start with a small liquid universe, ideally 10 to 25 stocks from NIFTY 50 or NIFTY 100.

Universe filters:

- High average traded value
- High average volume
- Narrow bid-ask spread
- No frequent circuit behavior
- No illiquid small-caps
- No trade-to-trade restricted securities
- No manually blocked securities

The universe should be stored in a versioned config file.

## 6. Strategy lifecycle

Every strategy must move through this lifecycle:

```text
Draft
  -> implemented
  -> backtested
  -> reviewed
  -> paper enabled
  -> paper reviewed
  -> live approved
  -> live tiny size
  -> live scaled gradually
  -> retired or disabled if performance breaks
```

A strategy cannot go live unless:

- It has a versioned implementation.
- It has a versioned config.
- It has a completed backtest report.
- It has passed cost and slippage assumptions.
- It has passed paper trading review.
- It has a defined max capital allocation.
- It has a defined max daily loss.
- It has manual live approval.

## 7. Strategy interface requirement

Strategies must not call Zerodha directly.

A strategy receives market events and emits an `OrderIntent`.

Example:

```python
OrderIntent(
    strategy_id="orb_nifty100_v1",
    symbol="NSE:RELIANCE",
    side="BUY",
    quantity=10,
    order_type="LIMIT",
    price=2840.50,
    product="MIS",
    validity="DAY",
    reason="breakout_above_opening_range"
)
```

The risk engine decides whether the intent is allowed. The order manager decides how to place and track it.

## 8. Risk philosophy

The risk engine is more important than the strategy engine.

The system should reject trades more often than it accepts them if risk information is incomplete or stale.

Default rule:

```text
When uncertain, do not trade.
```

## 9. Dashboard requirements

The v1 dashboard should show:

- System status
- Zerodha connection status
- WebSocket status
- Trading mode
- Live trading enabled or disabled
- Active strategies
- Open positions
- Orders
- Trades
- Daily realized P&L
- Daily unrealized P&L
- Risk usage
- Last signal
- Last rejected order and reason
- Kill switch

## 10. Non-functional requirements

The system must be:

- Testable
- Modular
- Auditable
- Restart-safe
- Idempotent for order operations
- Config-driven
- Dockerized
- Git compatible
- Safe by default

## 11. Safety constraints

The system must not place live orders unless all of the following are true:

- `LIVE_TRADING_ENABLED=true`
- Strategy is live approved
- User has enabled the strategy
- Market data is fresh
- Broker connection is healthy
- Risk engine approves the trade
- Global kill switch is not active
- Daily loss limit has not been breached
- Order-rate limiter allows the order
- Broker reconciliation is healthy

## 12. Acceptance criteria

- Backtests produce trade-level logs and performance metrics.
- Paper trading can run without placing real orders.
- Live trading cannot run accidentally from local tests.
- Risk engine blocks invalid orders.
- Kill switch blocks all new orders.
- Broker adapter can be mocked in tests.
- Order placement is idempotent.
- Reconciliation can detect mismatch between internal and broker positions.
- All live order decisions are logged with reason codes.
