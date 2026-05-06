# Tests

Add tests as each milestone is implemented.

Critical safety tests:

- Live trading disabled by default
- Paper mode never calls real order placement
- Risk engine blocks kill-switch orders
- Duplicate order intents do not create duplicate broker orders
- Unknown order states block new orders until reconciliation
