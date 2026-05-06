# Stock Trading Engine

A personal Zerodha-connected Indian equity intraday trading engine.

**Asset class:** NSE cash equities only.
**Broker:** Zerodha Kite Connect.
**Style:** Intraday day trading (MIS product).
**Modes:** Backtest → Paper trading → Live trading.

---

## Safety warning

> **Live trading is disabled by default.**
>
> `LIVE_TRADING_ENABLED` defaults to `false`. The broker interface raises
> `LiveTradingDisabledError` on any order placement attempt. Live execution
> requires a complete order manager, risk engine, and reconciliation system
> (Milestone 9) before this flag can safely be set to `true`.

---

## Current milestone

**Milestone 5 — Event-Driven Backtesting Engine** (complete)

Added a complete offline backtesting framework. No live broker, no Zerodha calls,
no real order placement at any point in this milestone.

**How the backtester works:**

1. `HistoricalDataFeed` accepts one or more symbol DataFrames, merges them, and
   yields `(timestamp, symbol, Bar)` tuples in chronological order.
2. `BacktestEngine` iterates the feed, calls `strategy.on_bar()` per bar, and
   routes `OrderIntent` objects to `SimulatedBroker`.
3. `SimulatedBroker` applies slippage via `SlippageModel`, calculates fees via
   `CostModel`, and creates `TradeFill` objects, then updates `BacktestPortfolio`.
4. After each bar the portfolio is marked to market and equity is recorded.
5. At the end, `calculate_backtest_metrics()` computes summary statistics and
   `BacktestEngine.run()` returns a `BacktestReport` (JSON-serialisable).

**Supported in v1:**
- MARKET orders (fill at bar close ± slippage)
- LIMIT orders (BUY fills if bar.low ≤ limit; SELL fills if bar.high ≥ limit)
- Long-only positions
- Indian equity intraday fee model (brokerage, STT, exchange charge, SEBI, stamp, GST)
- Configurable slippage in basis points
- Per-run `BacktestReport` with equity curve, fills, and metrics (total return,
  max drawdown, win rate, profit factor, expectancy)
- JSON report serialisation via `report.save_json(path)`

**Intentionally not supported yet:**
- SL / SL-M orders (raise `UnsupportedOrderTypeError`)
- Short selling
- Risk engine limits (placeholder `_risk_check()` always approves)
- Multiple partial fills per bar
- Tick-level simulation

No Zerodha SDK is imported anywhere in the backtest package.

```bash
python3 -m pytest -v          # 417 tests, all pass
python3 -m ruff check src tests   # clean
python3 -m ruff format --check src tests  # clean
```

---

**Milestone 4 — Historical Data Pipeline** (complete)

Added a complete historical data acquisition pipeline:

- **`data/universe.py`** — `UniverseConfig` (Pydantic v2): validates symbol list
  (non-empty, no duplicates, no blank strings), defaults exchange to NSE, carries
  optional `filters` dict. `load_universe_config(path)` reads any YAML file that
  contains a `universe:` section. Default config has 10 liquid NSE large-caps.
- **`data/validation.py`** — `validate_ohlcv_dataframe(df, symbol, exchange, interval)`:
  returns a `DataValidationReport` with typed `DataValidationIssue` entries (severity
  `"error"` or `"warning"`). Checks: required columns, empty df, duplicate timestamps,
  positive OHLC prices, non-negative volume, correct high ≥ open/close/low, low ≤
  open/close/high, sorted timestamps, and intraday gap detection (warning, not error).
- **`data/historical.py`** — `HistoricalDataDownloader(broker, data_dir)`: downloads
  Zerodha candle dicts via injected broker, normalises `"date"` → `"timestamp"`,
  coerces numeric types, validates, and optionally saves as Parquet.
  Storage layout: `DATA_DIR/candles/{exchange}/{symbol}/{interval}.parquet`.
  `download_universe(instruments, universe, ...)` iterates the full symbol list.
- **`storage/models.py`** — `HistoricalCandlesMetadata` ORM model: tracks per-symbol
  download runs, file path, candle count, validation status.
- **`configs/default.yaml`** — expanded universe to 10 symbols with filters section.

```bash
python3 -m pytest -v   # 297 tests, all pass
```

---

**Milestone 3 — Zerodha Read-Only Broker Adapter** (complete)

Added Zerodha broker integration and a safe paper broker:

- **`broker/zerodha/auth.py`** — `KiteAuthManager`: handles the Zerodha login URL
  → request_token → access_token flow via dependency-injected Kite client.
  Credentials held as `SecretStr`; raw values extracted only at SDK call boundaries.
  Never logs or returns secrets in repr.
- **`broker/zerodha/client.py`** — `ZerodhaBroker`: implements the abstract `Broker`
  interface. Wraps `kite_client.positions()`, `orders()`, `trades()`, `margins()`,
  `instruments()`, `historical_data()`. Requires `connect()` before data-fetching calls.
  `stream_ticks` raises `NotImplementedError` (Milestone 8). All order methods raise
  `LiveTradingDisabledError` (inherited from `Broker` base).
- **`broker/zerodha/mappers.py`** — placeholder for future Zerodha dict → internal model
  conversion.
- **`broker/paper.py`** — `PaperBroker`: safe simulated broker for paper trading.
  All read methods return empty/default values. Order methods raise `LiveTradingDisabledError`.

Why tests use fake clients: injecting a `FakeKiteClient` (defined in test files)
avoids any real Zerodha network calls. Tests run fully offline without credentials.

```bash
python3 -m pytest -v   # 212 tests, all pass
```

---

**Milestone 2 — Domain Models** (complete)

Added a broker-independent `trading_engine.domain` package containing:

- **`enums.py`** — `TradingMode`, `Exchange`, `Side`, `OrderType`, `ProductType`,
  `TimeInForce`, `OrderStatus`, `SignalType`, `RiskReasonCode` as `StrEnum`
  (members compare equal to their string values with no extra conversion needed)
- **`identifiers.py`** — `generate_internal_order_id()`, `generate_signal_id()`,
  `generate_risk_decision_id()`, `generate_fill_id()` — UUID4-based, prefixed
- **`models.py`** — Pydantic v2 models: `Money`, `Instrument`, `RiskDecision`,
  `InternalOrder`, `TradeFill`, `Position`, `PortfolioSnapshot`

Why broker-independent? The Zerodha SDK will be integrated in Milestone 3.
Domain models must be defined separately so the risk engine, backtester, and
paper engine can all use the same types without importing broker-specific code.

Live order placement is **still not implemented**. `Broker.place_order()` still
raises `LiveTradingDisabledError`. This will remain so until Milestone 9.

```bash
python3 -m pytest -v   # 151 tests, all pass
```

---

**Milestone 1 — Foundation** (complete)

- Pydantic Settings-based configuration with safe defaults
- Structured JSON logging with automatic secret redaction
- Core domain models: `Bar`, `Tick`, `OrderIntent`, `Signal`, `StrategyContext`
- Abstract `Strategy` base class
- Abstract `Broker` interface with live order placement blocked
- SQLAlchemy database scaffolding with health check
- Clock abstraction for backtest / live time control
- Custom exception hierarchy

**Milestone 3** — Zerodha read-only integration (next)

---

## Repository structure

```
src/trading_engine/
  common/         config, logging, exceptions, clock
  broker/         abstract Broker interface + zerodha/ stub
  strategy/       Strategy base class, Bar/Tick/OrderIntent models
  data/           (Milestone 4)
  backtest/       (Milestone 6)
  execution/      (Milestone 9)
  risk/           (Milestone 7)
  portfolio/      (Milestone 6+)
  storage/        SQLAlchemy base + health check

tests/
  unit/           test_config, test_logging, test_strategy_base
  integration/    (future)

configs/
  default.yaml        active config (gitignored if it has secrets)
  config.example.yaml reference config

docs/               full specification documents
```

---

## Local setup

### Prerequisites

- Python 3.11+
- Docker + Docker Compose (for PostgreSQL)
- Zerodha Kite Connect API credentials (not required for backtest mode)

### 1. Clone and install

```bash
git clone <repo-url>
cd <repo-dir>
make install
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your values. At minimum for local development:

```env
APP_ENV=development
LOG_LEVEL=INFO
DATABASE_URL=postgresql+psycopg://trading:trading@localhost:5432/trading_engine

# Zerodha — leave blank until Milestone 3
ZERODHA_API_KEY=
ZERODHA_API_SECRET=
ZERODHA_ACCESS_TOKEN=

# Safety flags — do NOT change LIVE_TRADING_ENABLED until Milestone 9
LIVE_TRADING_ENABLED=false
PAPER_TRADING_ENABLED=true

# Risk limits (INR)
MAX_DAILY_LOSS=1000
MAX_ORDER_VALUE=10000
MAX_TRADES_PER_DAY=20
ORDER_RATE_LIMIT_PER_SECOND=1
```

### 3. Start PostgreSQL

```bash
make up       # starts postgres (and redis) via docker compose
```

### 4. Copy config

```bash
cp configs/config.example.yaml configs/default.yaml
```

---

## Running tests

```bash
make test           # run all tests
make test-cov       # run tests with coverage report
```

All tests pass without a live Zerodha connection or a running database.

---

## Development commands

```bash
make install        # install package and dev dependencies
make test           # pytest
make test-cov       # pytest with coverage
make lint           # ruff check
make format         # ruff format
make typecheck      # mypy
make up             # start docker services
make down           # stop docker services
make run-dashboard  # placeholder (Milestone 10)
```

---

## Adding a strategy

Subclass `Strategy` and implement `on_bar()`:

```python
from trading_engine.strategy.base import Strategy, StrategyContext
from trading_engine.strategy.signals import Bar, OrderIntent
from decimal import Decimal

class MyStrategy(Strategy):
    def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
        # Analyse bar, return zero or more OrderIntents.
        # Do NOT call the broker here.
        return []
```

Strategies must never import Zerodha SDK modules. They emit `OrderIntent`
objects; the risk engine and order manager handle the rest.

---

## Next milestone

**Milestone 4: Historical data pipeline**

- Instrument universe config (YAML-driven symbol list)
- Historical candle downloader using `ZerodhaBroker.get_historical_data()`
- Store candles as Parquet files (pandas)
- Metadata index in database (table: `historical_candles_metadata`)
- Data validation: missing candles, duplicates, bad prices, corporate action notes
- Tests with fake candle data — no real Zerodha calls

See `docs/05_claude_prompt_pack.md` (Prompt 4 — historical data) for context.

---

## Documentation

| File | Contents |
|------|----------|
| `docs/00_personal_trading_engine_spec.md` | Full product spec |
| `docs/01_technical_architecture.md` | Architecture overview |
| `docs/02_risk_management_spec.md` | Risk engine design |
| `docs/03_backtesting_methodology.md` | Backtesting approach |
| `docs/04_implementation_plan.md` | All 12 milestones |
| `docs/05_claude_prompt_pack.md` | Prompts for each milestone |
| `docs/07_acceptance_checklists.md` | Go-live criteria |

---

## Operating principle

```
Strategy idea
  -> backtest
  -> validation and out-of-sample review
  -> paper trading
  -> tiny-size live trading
  -> gradual scale-up only after review
```

Strategies emit `OrderIntent` objects. The risk engine and order manager
decide whether an order can be placed. Strategies never touch the broker.

---

*This is not financial advice. The purpose of this project is to build a
safer, testable, auditable trading software system.*
