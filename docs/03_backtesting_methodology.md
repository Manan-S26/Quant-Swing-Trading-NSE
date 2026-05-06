# Backtesting Methodology

## 1. Goal

The backtesting engine should estimate whether a strategy has a reasonable edge after realistic costs, slippage, and execution assumptions.

It should not be used to prove that a strategy will make money. It should be used to reject weak strategies and identify candidates for paper trading.

## 2. Required design

Use an event-driven backtester, not only vectorized notebook logic.

Event-driven backtesting better matches live trading because decisions happen step by step, with portfolio state, risk limits, and order handling updated over time.

## 3. Data requirements

For each candle:

- timestamp
- exchange
- symbol
- open
- high
- low
- close
- volume
- open interest if applicable and available

For intraday strategies, store at least minute-level candles if available.

## 4. Data validation

Before using historical data, validate:

- Missing candles
- Duplicate candles
- Bad timestamps
- Zero or negative prices
- Outlier candles
- Corporate action adjustment assumptions
- Exchange holidays
- Session boundaries

## 5. Backtest event flow

```text
Initialize portfolio
Initialize strategy
Load candles
For each timestamp:
  Update market snapshot
  Send event to strategy
  Receive order intents
  Run risk engine
  Simulate fills
  Update positions
  Update P&L
  Log events
At end:
  Square off intraday positions
  Generate report
```

## 6. Fill simulation

The fill model should support:

- Market order fill at next tradable price plus slippage
- Limit order fill only if price is touched
- Stop-loss trigger simulation
- Partial fill assumptions
- No fill when volume or liquidity is insufficient

Start simple, then improve.

V1 fill model:

- Market orders fill at next candle open plus slippage.
- Buy limit orders fill if candle low <= limit price.
- Sell limit orders fill if candle high >= limit price.
- Stop orders trigger if trigger price is crossed.
- End-of-day square-off at market close candle.

## 7. Cost model

The cost model should include:

- Brokerage
- STT
- Exchange transaction charges
- SEBI charges
- Stamp duty
- GST on brokerage and transaction charges
- Slippage

Cost parameters should be configurable so they can be updated without code changes.

## 8. Slippage model

Start with configurable bps slippage.

Examples:

```text
large_cap_slippage_bps = 2
mid_cap_slippage_bps = 5
stress_slippage_bps = 10
```

Test strategies under multiple slippage assumptions.

## 9. Performance metrics

Required metrics:

- Total return
- Daily P&L
- Monthly P&L
- Win rate
- Loss rate
- Average win
- Average loss
- Expectancy
- Profit factor
- Max drawdown
- Sharpe ratio
- Sortino ratio
- Number of trades
- Turnover
- Costs paid
- Slippage paid
- Best trade
- Worst trade
- Longest losing streak
- Average holding time

## 10. Trade log

Every backtest must produce a trade-level log:

- strategy_id
- strategy_version
- symbol
- side
- entry_time
- entry_price
- exit_time
- exit_price
- quantity
- gross_pnl
- costs
- slippage
- net_pnl
- reason_entry
- reason_exit

## 11. Validation gates

A strategy should not advance to paper trading unless:

- It has enough trades to be meaningful.
- It remains profitable after costs and slippage.
- Drawdown is within limit.
- No single trade explains most profits.
- No single day explains most profits.
- Performance is acceptable across multiple market regimes.
- Out-of-sample results are not materially worse than in-sample results.

## 12. Walk-forward testing

Split historical data into windows:

```text
Train or parameter selection window
Validation window
Out-of-sample window
```

Avoid optimizing parameters repeatedly on the same full dataset.

## 13. Overfitting warnings

Be suspicious if:

- Strategy has too many parameters.
- Small parameter changes destroy results.
- Results depend on one stock.
- Results depend on one month.
- Backtest ignores costs.
- Strategy trades illiquid names.
- Strategy assumes perfect fills.
- Strategy produces unusually smooth returns.

## 14. Backtest report format

Each report should include:

- Summary table
- Equity curve
- Drawdown curve
- Daily P&L
- Monthly P&L
- Trade list
- Cost analysis
- Slippage sensitivity
- Parameter summary
- Data coverage summary
- Known limitations

## 15. Promotion to paper trading

A strategy can move to paper trading only when:

- Backtest report is saved.
- Risk config is defined.
- Strategy config is versioned.
- Known limitations are documented.
- User manually approves the strategy for paper mode.
