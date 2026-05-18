# Incident Response Guide

**Version:** Milestone 17
**Scope:** NSE cash equities, Zerodha Kite Connect, intraday MIS
**Purpose:** Step-by-step actions for known failure scenarios during a live pilot session.

> **First rule:** When in doubt, close all positions manually via Kite and stop for the day.
> Do not debug a live position.

---

## Immediate Stop Procedure (Any Incident)

Before investigating any incident, secure your positions:

1. Open Kite web app (kite.zerodha.com) or Kite mobile app.
2. Navigate to **Positions** tab.
3. If any open position exists: click **Exit** on each position.
4. Navigate to **Orders** tab.
5. Cancel any open (pending) orders.
6. Activate kill switch in code: set `GLOBAL_KILL_SWITCH=true` in `.env`.
7. Stop any running scripts: `Ctrl+C`.

Then investigate.

---

## Incident 1: Wrong Order Was Placed

**Symptoms:** `broker_order_id` returned but symbol/side/quantity does not match intent.

**Actions:**

1. **Immediately** open Kite Orders tab.
2. Identify the wrong order.
3. If status is **OPEN**: click Cancel immediately.
4. If status is **COMPLETE** (filled): open Positions tab and exit the position at market.
5. Record the fill price, time, and P&L impact in your trading journal.
6. Check audit log for what was actually submitted:
   ```bash
   tail -20 data/audit/pilot_orders.jsonl | python3 -m json.tool
   ```
7. Compare `raw_intent` in the audit log vs. what appeared in Kite.
8. Do not place any more orders until root cause is identified.
9. Root causes to investigate:
   - Incorrect CLI arguments.
   - Stale `LIVE_ALLOWED_SYMBOLS` config allowing wrong symbol.
   - Duplicate script invocation.

---

## Incident 2: Order Status Is Unknown

**Symptoms:** Script completed but no `broker_order_id` in output, OR broker_order_id returned but order not visible in Kite.

**Actions:**

1. Open Kite Orders tab and search for any order placed in the last 5 minutes.
2. If order appears: note status (OPEN/COMPLETE/REJECTED) and treat as known.
3. If order does NOT appear after 30 seconds:
   - The order was likely not placed (network error, safety check failed).
   - Check script stderr for error messages.
   - Check audit log: `tail -10 data/audit/pilot_orders.jsonl`.
   - Check Kite margin usage — if unchanged, order was not placed.
4. Do not place a second order until first order status is confirmed.
5. If using `OrderVerificationService`, its output will show `found: false` — treat as not placed.

---

## Incident 3: Broker API Timeout

**Symptoms:** `place_order()` raises `ConnectionError`, `Timeout`, or `NetworkException` from kiteconnect.

**Actions:**

1. Check Kite status page: status.zerodha.com.
2. Verify internet connectivity: `ping 8.8.8.8`.
3. Verify Zerodha API is reachable: `curl -s https://api.kite.trade/` (should return JSON).
4. Check if the order was placed despite the timeout:
   - Open Kite Orders tab immediately.
   - If the order appears: treat as placed and proceed with Incident 2 flow if uncertain.
   - If the order does NOT appear: the order was not placed. Safe to retry after connectivity is restored.
5. Do not retry automatically. Confirm order status manually before any retry.
6. If retrying after a timeout: verify no duplicate order exists in Kite first.

---

## Incident 4: WebSocket Disconnects (Paper Live Mode)

**Symptoms:** `run_paper_live_zerodha.py` stops receiving ticks. Dashboard shows stale timestamp.

**Actions:**

1. This does not affect live order placement (WebSocket is for market data only).
2. In paper mode: no real positions exist. Safe to restart.
3. Stop the script: `Ctrl+C`.
4. Wait 30 seconds for WebSocket connections to fully close.
5. Restart: `python3 scripts/run_paper_live_zerodha.py --i-understand-this-uses-live-market-data [args]`.
6. If disconnects are frequent: check network stability and Zerodha WebSocket status.

---

## Incident 5: Database / Dashboard Fails

**Symptoms:** Dashboard shows error, or `session_status.json` is malformed/missing.

**Actions:**

1. Dashboard failure does NOT affect order execution. Orders can still be placed.
2. The live pilot does not depend on the dashboard for order routing.
3. To reset dashboard: delete stale session file:
   ```bash
   rm data/dashboard/session_status.json
   ```
4. Restart dashboard if desired: `make run-dashboard`.
5. If PostgreSQL is down: execution and paper trading continue without DB.
   Reconciliation that requires DB will fail — use Kite web UI for reconciliation instead.

---

## Incident 6: Kill Switch Triggers

**Symptoms:** `assert_pilot_order_allowed()` or `assert_live_execution_allowed()` raises `SafetyError: Kill switch is active`.

**Actions:**

1. Kill switch triggered means the system detected a risk breach.
2. Open Kite: close all open positions before investigating.
3. Check audit logs for what triggered the kill switch:
   ```bash
   grep "kill_switch" data/audit/pilot_orders.jsonl
   ```
4. Check `KillSwitch.reason` (logged at activation time).
5. Common triggers: daily loss limit, manual activation, code bug.
6. Only deactivate the kill switch after root cause is understood and positions are flat.
7. To deactivate: set `GLOBAL_KILL_SWITCH=false` in `.env` and restart.

---

## Incident 7: Reconciliation Mismatch

**Symptoms:** `ReconciliationReport` shows discrepancies — orders in broker not in ledger, or status mismatches.

**Actions:**

1. **Do not place any new orders** until reconciliation is clean.
2. Open Kite Orders and Positions tabs and record all open orders/positions manually.
3. Run reconciliation (if service is available) and review the full report.
4. HIGH severity discrepancies (unknown broker orders):
   - These may represent orders from a different session, manual orders, or duplicate submissions.
   - Each must be investigated manually.
5. Status mismatches (ledger says SUBMITTED, broker says COMPLETE):
   - Update your local understanding. The broker is the source of truth.
6. Missing orders (in ledger but not at broker):
   - These orders were never placed or were rejected before reaching the broker.
   - No action needed but investigate root cause.
7. Close any unexpected open positions immediately via Kite.

---

## Incident 8: Local Machine Disconnects or Crashes

**Symptoms:** Script process killed mid-execution. Machine reboots or hibernates.

**Actions:**

1. **Immediately** check Kite Orders and Positions on mobile or another device.
2. The engine stores no persistent state after a crash. The broker holds the ground truth.
3. If an order was placed before the crash:
   - Identify it in Kite Orders.
   - If OPEN: decide whether to cancel or let fill. Kite does not auto-cancel.
   - If COMPLETE: you have a live position. Manage it via Kite manually.
4. Do not restart the script and place the same order again without confirming the crash left no open orders.
5. MIS positions must still be closed by 15:15 IST even if your machine is offline.
   Use Kite mobile app to close positions if necessary.

---

## Manual Kite Actions Reference

### View Positions

- Kite Web: kite.zerodha.com → Positions
- Kite App: Home → Positions tab

### Exit a Position

- Kite Web: Positions → Click on position → Exit (market order)
- Or: Place a reverse order manually.

### Cancel an Order

- Kite Web: Orders → Pending orders → Cancel

### View Order History

- Kite Web: Orders → Select order → View Order History (shows all state transitions)

### Check Margin

- Kite Web: Dashboard → Funds (shows available cash and used margin)

### Download Trade Book

- Kite Web: Reports → Trade Book → Download CSV (for reconciliation)

### Contact Zerodha Support

- Support: support.zerodha.com
- Hours: 8:00–18:00 IST, Mon–Fri
- Have your Client ID and order IDs ready.

---

## Post-Incident Documentation

After every incident:

1. Record in trading journal: time, incident type, orders affected, actions taken, outcome.
2. Update `docs/SAFETY_REVIEW.md` Known Limitations if a new failure mode was discovered.
3. Add a regression test if a code bug was the root cause.
4. Review whether any checklist item in `docs/OPERATING_CHECKLIST.md` needs updating.
