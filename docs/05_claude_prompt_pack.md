# Claude Prompt Pack

Use these prompts one at a time. Do not ask Claude to build the entire trading engine in a single prompt.

## Prompt 1: Foundation

```text
You are implementing a Python trading engine repository from an existing spec. Create the project skeleton only.

Requirements:
- Use a src layout.
- Create packages under src/trading_engine: broker, data, strategy, backtest, execution, risk, portfolio, storage, common.
- Add pyproject.toml with pytest, ruff, mypy, pydantic, pandas, numpy, sqlalchemy, psycopg, streamlit, pyyaml, python-dotenv.
- Add .gitignore, .env.example, Dockerfile, docker-compose.yml, Makefile.
- Add a config loader that reads YAML plus environment variables.
- Add structured logging setup.
- Add basic pytest test that imports the package.
- Do not implement broker order placement.
- Do not include secrets.

Return changed files and explain how to run tests.
```

## Prompt 2: Core models

```text
Implement the core domain models for the trading engine.

Requirements:
- Use Pydantic models.
- Add enums for TradingMode, Side, OrderType, ProductType, OrderStatus, TimeInForce.
- Add Bar, Tick, OrderIntent, RiskDecision, InternalOrder, TradeFill, Position.
- Validate positive quantity and price where required.
- Add reason and metadata fields for auditability.
- Add unit tests for valid and invalid model creation.
- Do not add broker-specific Zerodha logic yet.
```

## Prompt 3: Zerodha read-only broker adapter

```text
Implement the Zerodha broker adapter in read-only mode.

Requirements:
- Create a Broker base interface.
- Create ZerodhaBroker using dependency injection for the Kite client.
- Implement methods for profile, margins, instruments, positions, orders, trades, and historical candles.
- Implement live market data wrapper skeleton but keep it testable with mocks.
- Do not implement place_order, modify_order, or cancel_order yet. These should raise LiveTradingDisabled or NotImplementedError.
- Add unit tests using a fake Kite client.
- Never call real Zerodha APIs in tests.
```

## Prompt 4: Strategy interface

```text
Implement the strategy framework.

Requirements:
- Create Strategy base class with on_start, on_bar, on_tick, on_order_update, on_stop.
- Create StrategyContext containing clock, portfolio snapshot, config, mode, and logger.
- Create StrategyRegistry to register and instantiate strategies by name and version.
- Strategies must return OrderIntent objects only.
- Add a sample opening range breakout strategy for NSE stocks.
- Add tests with mocked bars.
```

## Prompt 5: Backtesting engine

```text
Implement an event-driven backtesting engine.

Requirements:
- Load historical Bar objects.
- Run one or more strategies over bars.
- Pass emitted OrderIntent objects to the risk engine.
- Use a SimulatedBroker to fill orders.
- Track positions and P&L.
- Include configurable cost model and slippage model.
- Generate a result object with trades, daily P&L, total return, win rate, profit factor, max drawdown, and costs.
- Add tests for a deterministic sample strategy.
```

## Prompt 6: Cost and slippage models

```text
Implement configurable cost and slippage models for Indian intraday equity trading.

Requirements:
- Do not hard-code values in strategy logic.
- Use a YAML config for brokerage, taxes, charges, and slippage bps.
- Implement a CostBreakdown model.
- Apply costs per trade.
- Add sensitivity support for normal, conservative, and stress slippage.
- Add unit tests.
```

## Prompt 7: Risk engine

```text
Implement the risk engine.

Requirements:
- Risk engine takes OrderIntent plus RiskContext and returns RiskDecision.
- Implement global limits, strategy limits, symbol limits, stale data check, trading window check, max daily loss, max order value, max open positions, and kill switch.
- Implement reason codes for every rejection.
- Default to reject if required information is missing.
- Add unit tests for each rejection path.
```

## Prompt 8: Paper trading engine

```text
Implement paper trading mode.

Requirements:
- Consume live or simulated ticks/bars.
- Run strategies exactly as live mode would.
- Run risk checks.
- Send approved intents to PaperBroker, not Zerodha.
- Track paper orders, fills, positions, and P&L.
- Log every signal, approval, rejection, and simulated fill.
- Add tests proving no real broker order method is called.
```

## Prompt 9: Live order manager

```text
Implement the live order manager with safety gates.

Requirements:
- Live order placement must require explicit LIVE_TRADING_ENABLED=true.
- Implement order state machine.
- Implement idempotency keys to prevent duplicate orders.
- Implement place, modify, cancel through Broker interface.
- Implement reconciliation with broker orders, trades, and positions.
- Unknown order states must block new orders until reconciled.
- Add tests that prove order placement is blocked by default.
- Use a fake broker in tests.
```

## Prompt 10: Streamlit dashboard

```text
Implement a Streamlit dashboard for the trading engine.

Pages:
- System status
- Strategy status
- Backtest reports
- Paper trading
- Live positions
- Orders
- Trades
- P&L
- Risk limits
- Kill switch
- Logs

Requirements:
- Dashboard should read data from repositories or API layer.
- Dashboard should not import strategy internals.
- Add a kill switch action that writes to the configured state store.
- Do not expose secrets.
```

## Prompt 11: Deployment

```text
Create deployment files for the trading engine.

Requirements:
- Dockerfile for the app.
- docker-compose.yml with postgres, optional redis, api, dashboard, live_runner, worker.
- Use environment variables for secrets.
- Add health checks.
- Add restart policies.
- Add persistent volumes.
- Add README instructions for local development and cloud VM deployment.
- Do not include actual credentials.
```

## Prompt 12: Final safety tests

```text
Add final safety test suite.

Tests must prove:
- Live trading is disabled by default.
- Strategies cannot call broker directly.
- Risk engine blocks orders when kill switch is active.
- Risk engine blocks orders when market data is stale.
- Order manager does not retry blindly after timeout.
- Duplicate intents do not create duplicate broker orders.
- Paper mode never calls real place_order.
- Disabled strategies cannot emit live orders.
```
