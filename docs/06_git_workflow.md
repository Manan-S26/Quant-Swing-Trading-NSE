# Git Workflow

## 1. Branching model

Use simple feature branches.

```text
main
  feature/foundation
  feature/core-models
  feature/zerodha-readonly
  feature/backtesting-engine
  feature/risk-engine
  feature/paper-trading
  feature/live-order-manager
  feature/dashboard
```

## 2. Commit style

Use clear conventional commits:

```text
feat: add core domain models
feat: add read-only Zerodha adapter
fix: prevent duplicate order submission
risk: add max daily loss rejection
backtest: add slippage model
chore: add docker compose
```

## 3. Pull request checklist

Every PR should include:

- What changed
- Why it changed
- Test evidence
- Risk impact
- Whether live order placement is touched
- Screenshots if dashboard changes

## 4. Protected files

Never commit:

- `.env`
- API keys
- API secrets
- Access tokens
- Broker session tokens
- Personal trading logs with account identifiers
- Full account statements

## 5. Required checks before merge

- Tests pass
- Lint passes
- Type checks pass where enabled
- No secrets detected
- No accidental live order calls in tests
- Risk tests pass if execution code changed

## 6. Suggested tags

Use git tags for important milestones:

```text
v0.1-foundation
v0.2-backtest-alpha
v0.3-paper-alpha
v0.4-risk-engine
v0.5-live-sandbox
```

## 7. Release discipline

Before each release:

- Update changelog
- Run full test suite
- Review risk config
- Verify live trading disabled by default
- Verify `.env.example` has no secrets
- Archive old backtest and paper results
