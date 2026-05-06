# Implementation Plan

## Milestone 1: Foundation

Goal: Create a runnable, testable project skeleton.

Tasks:

- Initialize Python project
- Add `src/` layout
- Add `.gitignore`
- Add `.env.example`
- Add config loader
- Add structured logging
- Add Docker Compose
- Add PostgreSQL service
- Add test framework
- Add Makefile

Acceptance criteria:

- `make test` runs
- `make lint` runs or is stubbed
- Docker services start
- Config can load from env and YAML
- No secrets committed

## Milestone 2: Core domain models

Goal: Define shared objects used across the engine.

Tasks:

- Create enums for side, order type, product, order status, trading mode
- Create models for Bar, Tick, OrderIntent, RiskDecision, InternalOrder, TradeFill, Position
- Add validation rules
- Add serialization support
- Add tests

Acceptance criteria:

- Models validate required fields
- Invalid orders fail fast
- Tests cover basic creation and validation

## Milestone 3: Zerodha read-only integration

Goal: Connect to Zerodha without placing orders.

Tasks:

- Implement Kite auth skeleton
- Load API key and secret from env
- Store access token securely
- Fetch profile
- Fetch margins
- Fetch instruments
- Fetch positions
- Fetch orders
- Fetch historical candles
- Connect to WebSocket for market data

Acceptance criteria:

- No order placement method is active yet
- Read-only methods can be mocked
- Integration code is isolated behind broker interface
- Tests use mock client, not real broker

## Milestone 4: Historical data pipeline

Goal: Store and validate candle data.

Tasks:

- Build instrument universe config
- Implement historical candle downloader
- Store candles as Parquet
- Add metadata index in database
- Validate missing candles
- Validate duplicate candles
- Validate bad prices

Acceptance criteria:

- Can store candles for a small stock universe
- Validation report is generated
- Backtester can load stored candles

## Milestone 5: Strategy interface and sample strategies

Goal: Let strategies run in any mode.

Tasks:

- Implement Strategy base class
- Implement StrategyContext
- Implement StrategyRegistry
- Implement sample opening range breakout strategy
- Implement sample VWAP trend strategy
- Add tests

Acceptance criteria:

- Strategy emits OrderIntent, not broker orders
- Strategy can run with mocked bar data
- Strategy config is versioned

## Milestone 6: Backtesting engine

Goal: Run realistic historical simulations.

Tasks:

- Implement event loop
- Implement simulated broker
- Implement fill model
- Implement cost model
- Implement portfolio tracker
- Implement metrics engine
- Implement report generator
- Add backtest CLI

Acceptance criteria:

- Can run a backtest on one strategy and one stock
- Trade log is generated
- Metrics report is generated
- Costs and slippage are included

## Milestone 7: Risk engine

Goal: Block unsafe orders.

Tasks:

- Implement global limits
- Implement strategy limits
- Implement symbol limits
- Implement stale data check
- Implement trading window check
- Implement kill switch
- Implement order-rate limiter
- Implement risk event logs
- Add tests for all rejection cases

Acceptance criteria:

- Risk engine approves and rejects correctly
- Kill switch blocks new orders
- Daily loss breach blocks new orders
- Tests prove invalid orders cannot pass

## Milestone 8: Paper trading engine

Goal: Run strategies live without real orders.

Tasks:

- Connect live market feed to strategy runner
- Build candle aggregator
- Implement paper broker
- Track paper positions and P&L
- Save paper trades
- Generate end-of-day paper report

Acceptance criteria:

- Paper trading runs during market hours
- No real broker order methods are called
- Paper P&L is tracked
- Dashboard shows paper status

## Milestone 9: Live order manager

Goal: Add controlled real order execution.

Tasks:

- Implement order state machine
- Implement idempotency keys
- Implement real Zerodha place order method
- Implement modify and cancel order
- Implement order status tracking
- Implement postback or polling update handler
- Implement reconciliation
- Implement duplicate prevention

Acceptance criteria:

- Live order placement requires explicit enablement
- Order state transitions are logged
- Duplicate orders are prevented
- Unknown statuses trigger reconciliation
- Tests cannot place real orders accidentally

## Milestone 10: Dashboard

Goal: Add operator visibility and control.

Tasks:

- Build Streamlit dashboard
- Show connection status
- Show active strategies
- Show orders
- Show trades
- Show positions
- Show P&L
- Show risk limits
- Add kill switch button
- Add config viewer

Acceptance criteria:

- Dashboard can be run locally
- User can see live/paper status
- User can activate soft kill switch
- Dashboard reads from database or API, not strategy internals

## Milestone 11: Deployment

Goal: Deploy safely to a controlled environment.

Tasks:

- Add Dockerfile
- Add Docker Compose services
- Configure PostgreSQL volume
- Configure environment files
- Add static-IP-ready deployment notes
- Add log rotation
- Add health checks
- Add restart policy

Acceptance criteria:

- Services restart cleanly
- No secrets in git
- Logs persist
- App can recover from restart without duplicate orders

## Milestone 12: Strategy approval workflow

Goal: Prevent unreviewed strategies from going live.

Tasks:

- Add strategy statuses
- Add backtest approval flag
- Add paper approval flag
- Add live approval flag
- Add strategy versioning
- Add config versioning
- Add review checklist

Acceptance criteria:

- Strategy cannot go live without approval
- Strategy version and config version are logged for every order
- Disabled strategy cannot emit live orders
