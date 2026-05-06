# Technical Architecture

## 1. Architecture principle

Separate strategy logic, broker integration, risk checks, data handling, execution, and portfolio accounting.

A strategy should never directly place a broker order. It should only emit an `OrderIntent`.

## 2. High-level architecture

```text
Market Data
  -> Data Layer
  -> Strategy Runner
  -> OrderIntent
  -> Risk Engine
  -> Order Manager
  -> Broker Adapter
  -> Zerodha

Broker Updates
  -> Order Manager
  -> Portfolio Engine
  -> Storage
  -> Dashboard
```

## 3. Runtime modes

The same strategy interface should run in three modes:

```text
Backtest mode: historical data + simulated broker
Paper mode: live data + simulated broker
Live mode: live data + real broker
```

## 4. Proposed repository structure

```text
src/trading_engine/
  broker/
    base.py
    zerodha.py
    models.py
    exceptions.py

  data/
    historical.py
    live_feed.py
    candle_builder.py
    instruments.py

  strategy/
    base.py
    registry.py
    context.py
    models.py

  backtest/
    engine.py
    simulated_broker.py
    fill_model.py
    cost_model.py
    metrics.py
    report.py

  execution/
    order_manager.py
    state_machine.py
    reconciliation.py
    idempotency.py

  risk/
    engine.py
    limits.py
    validators.py
    kill_switch.py
    rate_limiter.py

  portfolio/
    positions.py
    pnl.py
    exposure.py

  storage/
    models.py
    repositories.py
    migrations/

  common/
    config.py
    logging.py
    clock.py
    enums.py
    errors.py
```

## 5. Core domain objects

### OrderIntent

Represents what a strategy wants to do.

Fields:

- strategy_id
- strategy_version
- symbol
- exchange
- side
- quantity
- order_type
- product
- price
- trigger_price
- validity
- reason
- timestamp
- metadata

### RiskDecision

Represents risk engine approval or rejection.

Fields:

- intent_id
- approved
- reason_code
- reason_message
- checked_limits
- timestamp

### InternalOrder

Represents an order tracked by the system.

Fields:

- internal_order_id
- broker_order_id
- strategy_id
- symbol
- side
- quantity
- order_type
- product
- price
- trigger_price
- status
- risk_decision_id
- created_at
- updated_at
- raw_broker_response

### TradeFill

Represents an executed fill.

Fields:

- fill_id
- internal_order_id
- broker_order_id
- symbol
- side
- quantity
- price
- fees
- timestamp

## 6. Broker adapter

The broker adapter isolates Zerodha-specific code.

Interface:

```python
class Broker:
    def place_order(self, order_request):
        raise NotImplementedError

    def modify_order(self, order_id, changes):
        raise NotImplementedError

    def cancel_order(self, order_id):
        raise NotImplementedError

    def get_orders(self):
        raise NotImplementedError

    def get_trades(self):
        raise NotImplementedError

    def get_positions(self):
        raise NotImplementedError

    def get_margins(self):
        raise NotImplementedError
```

In v1, implement:

- ZerodhaBroker
- SimulatedBroker
- PaperBroker

## 7. Strategy interface

```python
class Strategy:
    def on_start(self, context):
        pass

    def on_bar(self, bar, context):
        return []

    def on_tick(self, tick, context):
        return []

    def on_order_update(self, order_update, context):
        pass

    def on_stop(self, context):
        pass
```

Strategies return zero or more `OrderIntent` objects.

## 8. Backtesting engine

The backtester should be event-driven.

Flow:

```text
Load historical data
Initialize strategy
For each candle:
  Update clock
  Send candle to strategy
  Collect order intents
  Run risk engine
  Send approved orders to simulated broker
  Simulate fills
  Update portfolio
  Log events
Generate report
```

## 9. Paper trading engine

Flow:

```text
Connect to Zerodha WebSocket
Subscribe to universe
Build candles
Run strategy
Run risk engine
Send approved order intents to paper broker
Simulate fills
Track paper P&L
Display results
```

## 10. Live trading engine

Flow:

```text
Connect to Zerodha WebSocket
Load approved strategies
Receive live ticks or bars
Run strategy
Run risk engine
Submit approved orders to order manager
Place broker order
Track order status
Reconcile with broker state
Update portfolio
Alert on events
```

## 11. Order state machine

Supported states:

```text
CREATED
RISK_APPROVED
RISK_REJECTED
SUBMITTED
OPEN
PARTIALLY_FILLED
FILLED
CANCEL_REQUESTED
CANCELLED
REJECTED
FAILED
UNKNOWN
RECONCILED
```

Rules:

- Every state transition must be logged.
- Unknown state should trigger reconciliation.
- Failed placement should not blindly retry.
- Duplicate prevention must be implemented before live trading.

## 12. Database design

Suggested tables:

- strategies
- strategy_versions
- strategy_configs
- instruments
- historical_candles_metadata
- backtest_runs
- backtest_trades
- paper_runs
- paper_orders
- live_orders
- live_trades
- positions
- daily_pnl
- risk_events
- system_events
- broker_reconciliations

## 13. Deployment architecture

MVP deployment:

```text
Docker Compose
  api
  dashboard
  worker
  live_runner
  postgres
  redis optional
```

Production-like deployment:

```text
Cloud VM with static IP
Docker Compose or systemd services
PostgreSQL
Persistent disk for data
Encrypted env secrets
Alerting channel
Daily log rotation
```

## 14. Configuration

All environment-specific settings should come from config files or environment variables.

Examples:

- TRADING_MODE
- LIVE_TRADING_ENABLED
- ZERODHA_API_KEY
- ZERODHA_API_SECRET
- ZERODHA_ACCESS_TOKEN
- DATABASE_URL
- MAX_DAILY_LOSS
- MAX_ORDER_VALUE
- MAX_OPEN_POSITIONS
- GLOBAL_KILL_SWITCH

## 15. Testing strategy

Required test categories:

- Unit tests for strategy logic
- Unit tests for risk rules
- Unit tests for order state machine
- Unit tests for cost model
- Unit tests for fill model
- Integration tests with mocked broker
- Backtest regression tests
- Paper trading dry-run tests
- No-live-order safety tests

Critical test:

```text
Tests must prove live order placement cannot happen unless explicitly enabled.
```
