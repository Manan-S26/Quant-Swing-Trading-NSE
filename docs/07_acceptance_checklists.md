# Acceptance Checklists

## 1. Before any live order code exists

- [ ] Repo skeleton exists
- [ ] Tests run
- [ ] Config loader works
- [ ] Secrets are not committed
- [ ] Broker interface is abstracted
- [ ] Strategies emit OrderIntent only

## 2. Before backtesting is trusted

- [ ] Historical data validation exists
- [ ] Cost model exists
- [ ] Slippage model exists
- [ ] Trade logs are generated
- [ ] Daily P&L is generated
- [ ] Drawdown is calculated
- [ ] Strategy config is versioned
- [ ] Backtest report includes assumptions

## 3. Before paper trading

- [ ] Live data feed works
- [ ] Paper broker exists
- [ ] Paper mode cannot place real orders
- [ ] Risk engine runs in paper mode
- [ ] Dashboard shows paper positions and P&L
- [ ] Paper trades are logged

## 4. Before live trading

- [ ] Live trading disabled by default
- [ ] Manual live enablement exists
- [ ] Strategy live approval exists
- [ ] Kill switch tested
- [ ] Max daily loss tested
- [ ] Stale data rejection tested
- [ ] Broker disconnect handling tested
- [ ] Reconciliation tested
- [ ] Duplicate prevention tested
- [ ] Order state machine tested
- [ ] Paper trading review completed
- [ ] Start with tiny quantity only

## 5. Daily startup checklist

- [ ] Confirm date and market session
- [ ] Confirm Zerodha session is active
- [ ] Confirm WebSocket is connected
- [ ] Confirm database is healthy
- [ ] Confirm strategy config
- [ ] Confirm risk limits
- [ ] Confirm live trading setting
- [ ] Confirm kill switch is off only if intentional
- [ ] Confirm no unexpected positions

## 6. Daily shutdown checklist

- [ ] Stop new orders before configured cutoff
- [ ] Square off intraday positions if required
- [ ] Reconcile broker positions
- [ ] Save order book
- [ ] Save trade book
- [ ] Save P&L report
- [ ] Archive logs
- [ ] Disable live trading if not needed

## 7. Incident checklist

Use this if anything unusual happens.

- [ ] Activate soft kill switch
- [ ] Check open orders
- [ ] Check open positions
- [ ] Reconcile against broker
- [ ] Cancel pending orders if needed
- [ ] Square off manually if needed
- [ ] Save logs
- [ ] Document incident
- [ ] Do not restart live trading until root cause is understood
