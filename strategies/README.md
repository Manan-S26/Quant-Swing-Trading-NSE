# Strategies

Each strategy should live in its own folder with:

- README
- strategy implementation
- config YAML
- tests
- backtest reports

Strategies must emit `OrderIntent` objects. They must not call Zerodha or any broker directly.
