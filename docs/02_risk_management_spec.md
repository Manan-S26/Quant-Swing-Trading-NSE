# Risk Management Spec

## 1. Risk principle

The risk engine is the core safety layer. It must sit between strategy output and order execution.

Default behavior:

```text
Reject if uncertain.
Reject if stale.
Reject if disconnected.
Reject if reconciliation is unhealthy.
Reject if limits are missing.
```

## 2. Risk engine inputs

The risk engine receives:

- OrderIntent
- Current positions
- Current cash and margins
- Strategy config
- Global risk config
- Latest market data
- Broker connection status
- Market data freshness status
- Daily P&L
- Order history
- Trade history
- Kill switch status

## 3. Risk engine output

The risk engine returns a `RiskDecision`:

```python
RiskDecision(
    approved=False,
    reason_code="MAX_DAILY_LOSS_BREACHED",
    reason_message="Daily loss limit reached. New orders blocked.",
    checked_limits=[...]
)
```

## 4. Global limits

Required global limits:

| Limit | Description |
|---|---|
| max_daily_loss | Maximum allowed realized plus unrealized loss for the day |
| max_gross_exposure | Maximum total exposure across positions |
| max_net_exposure | Maximum net directional exposure |
| max_open_positions | Maximum number of simultaneous open positions |
| max_order_value | Maximum value of a single order |
| max_orders_per_day | Maximum number of orders per day |
| max_orders_per_second | Internal order-rate cap |
| max_capital_deployed | Maximum capital deployed intraday |
| market_data_stale_seconds | Maximum allowed age of data before blocking orders |

## 5. Strategy limits

Each strategy must define:

- allowed_symbols
- max_capital
- max_position_value
- max_quantity_per_order
- max_trades_per_day
- max_daily_loss
- max_consecutive_losses
- allowed_order_types
- allowed_product_types
- trading_start_time
- trading_end_time
- square_off_time

## 6. Symbol-level limits

Each symbol can define:

- enabled or disabled
- max_position_value
- max_quantity
- min_average_volume
- min_average_traded_value
- max_allowed_spread
- max_intraday_volatility
- allow_shorting

## 7. Pre-trade checks

Before an order can be placed, verify:

- Global kill switch is off
- Live trading is explicitly enabled
- Strategy is approved for live mode
- Symbol is allowed
- Product is allowed
- Order type is allowed
- Trading window is open
- Quantity is positive
- Order value is within limits
- Position after order is within limits
- Daily loss is within limits
- Market data is fresh
- Broker connection is healthy
- Reconciliation is healthy
- Order-rate limit is not breached
- No duplicate intent is being processed

## 8. Runtime stop conditions

Stop all new orders if:

- Manual kill switch is triggered
- Max daily loss is breached
- Broker API is unavailable
- WebSocket disconnects and does not recover
- Market data is stale
- Database is unavailable
- Internal and broker positions mismatch
- Unknown order status persists
- Unexpected open position appears
- Order-rate limiter detects abnormal behavior

## 9. Kill switch behavior

The kill switch has two levels.

### Soft kill

- Block all new orders
- Keep monitoring existing orders
- Allow manual square-off
- Continue dashboard and logging

### Hard kill

- Block all new orders
- Cancel open pending orders where possible
- Alert user
- Optionally square off positions if configured
- Stop live strategy runners

## 10. Order-rate limiting

The system should include an internal order-rate limiter well below applicable broker or exchange thresholds.

Suggested v1 default:

```text
max_orders_per_second = 1
max_orders_per_minute = 20
max_orders_per_day = user-defined
```

The goal is not speed. The goal is safe controlled execution.

## 11. Position reconciliation

The system must compare internal state against broker state.

Reconcile:

- Open orders
- Completed orders
- Trades
- Positions
- Average price
- Realized P&L where available

If mismatch is detected:

```text
Block new orders
Mark reconciliation status unhealthy
Show alert
Require manual review or automated repair
```

## 12. Risk event logs

Every rejection and breach must be logged.

Fields:

- timestamp
- event_type
- strategy_id
- symbol
- order_intent_id
- rule_name
- approved
- reason_code
- reason_message
- input_snapshot

## 13. Live enablement checklist

Live trading can be enabled only if:

- Strategy has passed backtest review
- Strategy has passed paper trading review
- Strategy config is versioned
- Risk config is versioned
- Zerodha connection is healthy
- Static IP deployment plan is complete if required
- Kill switch has been tested
- Reconciliation has been tested
- No-live-order tests pass
- User has explicitly set `LIVE_TRADING_ENABLED=true`

## 14. Risk codes

Initial reason codes:

```text
GLOBAL_KILL_SWITCH_ACTIVE
LIVE_TRADING_DISABLED
STRATEGY_NOT_APPROVED
SYMBOL_NOT_ALLOWED
PRODUCT_NOT_ALLOWED
ORDER_TYPE_NOT_ALLOWED
OUTSIDE_TRADING_WINDOW
MAX_DAILY_LOSS_BREACHED
MAX_ORDER_VALUE_BREACHED
MAX_POSITION_VALUE_BREACHED
MAX_OPEN_POSITIONS_BREACHED
MARKET_DATA_STALE
BROKER_UNHEALTHY
RECONCILIATION_UNHEALTHY
ORDER_RATE_LIMIT_BREACHED
DUPLICATE_INTENT
INSUFFICIENT_MARGIN
UNKNOWN_RISK_ERROR
```
