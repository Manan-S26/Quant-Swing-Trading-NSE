# Safety Review — Live Order Execution

**Version:** Milestone 17 + safety patch
**Scope:** NSE cash equities, Zerodha Kite Connect, intraday MIS only
**Status:** Pilot-ready with all gates in place. Unattended live trading is intentionally not implemented.

---

## Overview

The engine enforces a multi-layer safety model. Every live order must pass all gates
in sequence before any Kite API call is made. No single flag, config setting, or code
path can bypass the full chain.

---

## Live Execution Gates

### Gate 1: Global kill switch

- **Location:** `src/trading_engine/risk/kill_switch.py`, `LiveExecutionSafetyGuard.assert_pilot_order_allowed()`
- **Default:** Inactive (starts inactive; must be explicitly activated).
- **Behaviour:** Once activated, all order placement paths raise `SafetyError` immediately.
  The kill switch is checked inside `assert_pilot_order_allowed()` before any broker call.
- **Live pilot:** `scripts/live_order_pilot.py` creates an in-process `KillSwitch` instance and
  passes it to `LiveExecutionSafetyGuard`. This in-process kill switch is scoped to the single
  pilot session. A persistent/shared kill switch (file-backed, DB-backed, or IPC-based) is
  future hardening and is not implemented in this milestone.
- **Recovery:** Deactivate via `kill_switch.deactivate()`.

### Gate 2: LIVE_TRADING_ENABLED flag

- **Location:** `src/trading_engine/common/config.py` (Settings),
  `LiveExecutionSafetyGuard.assert_pilot_order_allowed()` (check 0, enforced in code)
- **Default:** `False`
- **Behaviour:** `assert_pilot_order_allowed()` raises `SafetyError` if this flag is `False`.
  This is the first check in the pilot order gate — it runs before the execution flags, before
  the kill switch, and before any broker call. Setting `LIVE_TRADING_ENABLED=false` is
  sufficient to block all live pilot orders regardless of other flags.
  The download and paper scripts also refuse to run if this is `True` (inverted check).

### Gate 3: LIVE_ORDER_EXECUTION_ENABLED flag

- **Location:** `src/trading_engine/common/config.py`, `LiveExecutionSafetyGuard.assert_pilot_order_allowed()`
- **Default:** `False`
- **Behaviour:** `assert_pilot_order_allowed()` raises `SafetyError` if this is False.
  This flag must be explicitly set to `true` alongside `LIVE_TRADING_ENABLED`.

### Gate 4: LIVE_ORDER_PILOT_ENABLED flag

- **Location:** `src/trading_engine/common/config.py`, `LiveExecutionSafetyGuard.assert_pilot_order_allowed()`
- **Default:** `False`
- **Behaviour:** `assert_pilot_order_allowed()` raises `SafetyError` if this is False.
  Third required flag — all three must be simultaneously True.

### Gate 5: Terminal confirmation phrase

- **Location:** `scripts/live_order_pilot.py`
- **Phrase:** `PLACE LIVE ORDER` (exact, case-sensitive)
- **Behaviour:** The operator must type the exact phrase at the terminal. There is no `--yes`
  flag or other bypass. EOFError or wrong phrase returns exit code 4 and the order is not placed.
  Audit log records `decided_by="operator_cli"` and `reason="Terminal confirmation phrase matched."`
  to distinguish live-pilot approvals from paper-trading approvals.

### Gate 6: Approval status

- **Location:** `src/trading_engine/live_execution/approvals.py`, `LiveExecutionSafetyGuard.assert_pilot_order_allowed()`
- **Modes:**
  - `AUTO_PAPER`: Automatically approved (paper/dry-run only, or CLI pilot after terminal confirmation).
  - `MANUAL_APPROVE`: Creates a pending request and raises `ManualApprovalRequired`. No order is placed until `approve()` is called.
  - `AUTO_LIVE`: Raises `SafetyError` — not implemented. Cannot be used to bypass the manual review path.
- **Requirement:** `approval_decision.status` must be `APPROVED` before `assert_pilot_order_allowed()` passes.

### Gate 7: Risk engine approval

- **Location:** `src/trading_engine/risk/engine.py`, `LiveExecutionSafetyGuard.assert_pilot_order_allowed()`
- **Behaviour:** If a `risk_decision` is provided and `risk_decision.approved` is False,
  `assert_pilot_order_allowed()` raises `SafetyError`. The pilot executor also short-circuits
  before reaching the approval gate if risk rejects.
- **Checks:** Kill switch, symbol whitelist, product type, order type, order value,
  open position count, daily loss, trades per day, orders per second.

### Gate 8: Symbol whitelist

- **Location:** `LiveExecutionSafetyGuard.assert_pilot_order_allowed()`, `LivePilotConfig.allowed_symbols`
- **Default:** Empty list (all orders blocked when empty).
- **Behaviour:** Raises `SafetyError` if `LIVE_ALLOWED_SYMBOLS` is empty or the order's symbol
  is not in the whitelist. Case-insensitive comparison.

### Gate 9: Exchange constraint

- **Location:** `LiveExecutionSafetyGuard.assert_pilot_order_allowed()`, `LivePilotConfig.allowed_exchange`
- **Default:** `"NSE"`
- **Behaviour:** Raises `SafetyError` if `order_intent.exchange` does not match `LIVE_ALLOWED_EXCHANGE`.

### Gate 10: Product constraint

- **Location:** `LiveExecutionSafetyGuard.assert_pilot_order_allowed()`, `LivePilotConfig.allowed_product`
- **Default:** `"MIS"` (intraday only — auto-closed by broker at end of day)
- **Behaviour:** Raises `SafetyError` if product does not match `LIVE_ALLOWED_PRODUCT`.

### Gate 11: Order type constraint

- **Location:** `LiveExecutionSafetyGuard.assert_pilot_order_allowed()`, `LivePilotConfig.allowed_order_types`
- **Default:** `["MARKET", "LIMIT"]`
- **Behaviour:** Raises `SafetyError` if order type is not in the allowed list.

### Gate 12: Quantity cap

- **Location:** `LiveExecutionSafetyGuard.assert_pilot_order_allowed()`, `LivePilotConfig.max_order_quantity`
- **Default:** `1` (one share maximum)
- **Behaviour:** Raises `SafetyError` if `order_intent.quantity > max_order_quantity`.

### Gate 13: Broker connection guard

- **Location:** `ZerodhaBroker._require_connected()`, called at the start of `place_order()`
- **Behaviour:** Raises `BrokerConnectionError` if `broker.connect()` has not been called.

---

## Default-Disabled Flags Summary

| Flag | Default | Required for live orders |
|---|---|---|
| `LIVE_TRADING_ENABLED` | `false` | Yes |
| `LIVE_ORDER_EXECUTION_ENABLED` | `false` | Yes |
| `LIVE_ORDER_PILOT_ENABLED` | `false` | Yes |
| `LIVE_ALLOWED_SYMBOLS` | `[]` (empty) | Must be non-empty |
| `LIVE_MAX_ORDER_QUANTITY` | `1` | — |

---

## Audit Logging

- **Location:** `src/trading_engine/live_execution/audit.py`
- **Format:** JSONL (one JSON object per line, UTF-8 encoded)
- **Events logged:** `approval_request`, `approval_decision`, `dry_run_preview`
- **Path:** Configured in `LiveOrderPilotExecutor` (default: `data/audit/pilot_orders.jsonl`)
- **Secrets:** No secrets are logged. Audit records contain only order parameters and decisions.
- **Parent directories:** Created automatically on first write.

---

## Reconciliation

- **Location:** `src/trading_engine/reconciliation/service.py`
- **What it checks:** In-memory OrderLedger vs. live broker order list.
  Detects missing orders, status mismatches, and unknown broker orders.
- **Limitations:** Reconciliation is read-only. It detects discrepancies but does not auto-correct.
  Operator must review and take manual action for HIGH-severity discrepancies.

---

## Known Limitations

1. **No unattended automation:** There is no code path that executes a live order without
   a human explicitly running `live_order_pilot.py` and typing the confirmation phrase `PLACE LIVE ORDER`.
   There is no `--yes` flag or equivalent bypass.

2. **In-process kill switch only:** `live_order_pilot.py` creates an in-process `KillSwitch` that
   lives for the duration of the single pilot session. There is no persistent or shared kill switch
   (file-backed, DB-backed, IPC). If you need to block future sessions, set `LIVE_TRADING_ENABLED=false`
   in `.env` — this is enforced in code before any broker call.

3. **Single-session, in-memory state:** The `LiveOrderApprovalGate` and `OrderLedger` store
   state in memory only. If the process restarts mid-session, state is lost. Reconcile against
   broker after any restart.

3. **No position management:** The pilot places orders but does not manage exits, stop-losses,
   or take-profit levels automatically. The operator is responsible for closing positions.

4. **MIS auto-close risk:** If the position is not manually closed by 15:15 IST, Zerodha
   will auto-close MIS positions at approximately 15:20 IST at market price, which may
   result in slippage.

5. **Token expiry:** Zerodha access tokens expire daily. The engine does not auto-refresh tokens.
   A stale token causes all API calls to fail with 401.

6. **No WebSocket monitoring during pilot:** The live order pilot does not subscribe to
   a WebSocket feed. Order status is only known at placement time + manual Kite check.

7. **Rate limiting:** Zerodha enforces API rate limits. Repeated rapid calls may result
   in 429 errors. The engine does not implement backoff or retry beyond the broker SDK defaults.

8. **No automated order modification or cancellation:** `modify_order` and `cancel_order`
   still raise `LiveTradingDisabledError`. Manual action via Kite web/app required.

---

## What Is Intentionally Not Implemented

- Unattended automated live strategy execution.
- Automated strategy-to-live-order pipeline (strategy signals do not flow to live execution automatically).
- Auto scale-up (no logic to increase quantity based on P&L or confidence).
- Order modification or cancellation via this engine.
- Multiple simultaneous live orders in a single session.
- Live execution via `AUTO_LIVE` approval mode (raises `SafetyError`).
- Websocket-based position monitoring during live pilot.
- Auto-restart after process crash.
- Cloud deployment or remote execution.

---

## Security Considerations

- All Zerodha credentials are stored as `SecretStr` in `Settings` and are never logged,
  printed, or included in any repr output.
- `.env` is in `.gitignore`. Never commit credentials.
- Audit logs contain no secrets.
- The preflight checker confirms credential presence without revealing values.
