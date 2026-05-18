# Live Order Pilot Runbook

**Version:** Milestone 17
**Scope:** NSE cash equities, Zerodha Kite Connect, intraday MIS, single-share pilot
**Purpose:** Step-by-step guide for placing one real pilot order safely.

> **This guide places real orders with real money.**
> Complete the full Operating Checklist (docs/OPERATING_CHECKLIST.md) before starting.

---

## Step 0: Prerequisites

Before following this runbook:

- [ ] All 1196+ tests pass: `python3 -m pytest -q`
- [ ] Ruff passes: `python3 -m ruff check src tests scripts`
- [ ] You have a Zerodha account with API access enabled.
- [ ] You have a static IP whitelisted in Kite Connect settings.
- [ ] You have completed the full Operating Checklist.

---

## Step 1: Safe Dry-Run First

**Always run a dry run before the real pilot. This is mandatory.**

```bash
python3 scripts/live_order_dry_run.py \
  --symbol RELIANCE \
  --side BUY \
  --quantity 1 \
  --order-type MARKET
```

Expected output (abbreviated):
```json
{
  "symbol": "RELIANCE",
  "side": "BUY",
  "quantity": 1,
  "order_type": "MARKET",
  "approval_status": "approved",
  "message": "[DRY RUN] ...",
  "risk_decision": null
}
```

- Verify `approval_status` is `"approved"`.
- Verify `message` contains `"DRY RUN"`.
- No credentials required for this step.

---

## Step 2: Configure .env

Copy `.env.example` to `.env` if not already done:

```bash
cp .env.example .env
```

Edit `.env` and set these values:

```dotenv
# Zerodha credentials
ZERODHA_API_KEY=your_api_key_here
ZERODHA_API_SECRET=your_api_secret_here
ZERODHA_ACCESS_TOKEN=          # Fill in after Step 3

# Live trading flags — ALL must be true for pilot
LIVE_TRADING_ENABLED=true
LIVE_ORDER_EXECUTION_ENABLED=true
LIVE_ORDER_PILOT_ENABLED=true

# Pilot constraints — conservative for first run
LIVE_MAX_ORDER_QUANTITY=1
LIVE_ALLOWED_SYMBOLS=["RELIANCE"]
LIVE_ALLOWED_EXCHANGE=NSE
LIVE_ALLOWED_PRODUCT=MIS
LIVE_ALLOWED_ORDER_TYPES=["MARKET"]

# Risk limits
MAX_DAILY_LOSS=500
MAX_ORDER_VALUE=5000
MAX_OPEN_POSITIONS=1
MAX_TRADES_PER_DAY=3
MAX_ORDERS_PER_SECOND=1

# Kill switch — must be false
GLOBAL_KILL_SWITCH=false
```

**Security:**
- Never commit `.env` to git. Verify: `git status` — `.env` must NOT appear as staged.
- The `.gitignore` already excludes `.env`.

---

## Step 3: Generate Daily Access Token

Zerodha access tokens expire every day at midnight IST. Generate a fresh token each morning.

```bash
python3 scripts/zerodha_login_helper.py
```

Follow the prompts:
1. A browser URL will be displayed. Open it.
2. Log in to Zerodha with your client ID and password + TOTP.
3. After login, copy the `request_token` from the redirected URL.
4. Paste it back into the script.
5. The script will print your `access_token`.
6. Copy the token and set `ZERODHA_ACCESS_TOKEN=<token>` in `.env`.

**Verify the token works:**

```bash
python3 scripts/download_zerodha_historical.py --dry-run --symbols RELIANCE
```

Should exit 0 without API errors. If you see `401 Unauthorized`, regenerate the token.

---

## Step 4: Run Preflight Checks

```bash
python3 scripts/live_pilot_preflight.py
```

Review the output. All **REQUIRED** checks must show **PASS**.

For JSON output (for logging/scripting):

```bash
python3 scripts/live_pilot_preflight.py --json
```

Save the output for your records:

```bash
python3 scripts/live_pilot_preflight.py --json > data/audit/preflight_$(date +%Y%m%d_%H%M).json
```

If any required check FAILS, stop and resolve the issue before proceeding.

---

## Step 5: Run the One-Share Pilot

```bash
python3 scripts/live_order_pilot.py \
  --symbol RELIANCE \
  --side BUY \
  --quantity 1 \
  --order-type MARKET \
  --i-understand-this-places-real-orders
```

The script will display an order summary and prompt:

```
  WARNING: This will place a REAL order:
    Symbol:     RELIANCE
    Side:       BUY
    Quantity:   1
    Order type: MARKET
    Product:    MIS
    Exchange:   NSE

  Type "PLACE LIVE ORDER" to confirm:
```

### Exact Confirmation Phrase

Type exactly (case-sensitive, no extra spaces):

```
PLACE LIVE ORDER
```

Any other input will abort without placing the order.

---

## Step 6: Record the Broker Order ID

On success, the script prints JSON:

```json
{
  "success": true,
  "broker_order_id": "240315000123456",
  "approval_status": "approved",
  "error": null,
  "symbol": "RELIANCE",
  "side": "BUY",
  "quantity": 1,
  "order_type": "MARKET"
}
```

- **Record `broker_order_id` immediately.** Write it in your trading journal.
- This ID is needed for verification and reconciliation.

---

## Step 7: Verify the Order in Kite

1. Open kite.zerodha.com → Orders tab (or Kite mobile app → Orders).
2. Find the order with the matching `broker_order_id`.
3. Verify:
   - Symbol matches.
   - Side (BUY/SELL) matches.
   - Quantity = 1.
   - Status is OPEN or COMPLETE.
4. If status is REJECTED: note the rejection reason and do not retry without investigating.

---

## Step 8: Reconcile

Check the audit log:

```bash
tail -5 data/audit/pilot_orders.jsonl | python3 -m json.tool
```

Verify the logged intent matches what you intended to place.

If reconciliation scripts are available:

```bash
python3 -c "
from trading_engine.live_execution.order_verification import OrderVerificationService
# Requires a connected ZerodhaBroker instance
print('Manual verification: check Kite Orders tab for broker_order_id')
"
```

For the pilot, manual reconciliation via Kite Orders tab is sufficient.

---

## Step 9: Manage the Position

**Important:** The engine does NOT manage exits automatically.

- If the order was a BUY and you want to exit intraday:
  - Place a SELL order with the same parameters when ready.
  - Or use the Kite Orders tab to place a reverse order.
- **All MIS positions must be closed by 15:15 IST** to avoid the broker's auto-square-off
  at ~15:20 IST at potentially unfavourable prices.

---

## When to Stop

Stop the pilot session and close all positions if:

- Any unexpected order appears in Kite.
- P&L loss exceeds your daily limit.
- Kill switch activates.
- Reconciliation shows a discrepancy you cannot explain.
- You feel uncertain about any position.
- Any error occurs that you do not understand.

See `docs/INCIDENT_RESPONSE.md` for specific failure scenarios.

---

## What NOT to Do

- Do NOT automate the confirmation phrase (do not pipe input to the script).
- Do NOT run the pilot script in a cron job or background task.
- Do NOT set `LIVE_MAX_ORDER_QUANTITY > 1` until you have completed multiple 1-share pilots successfully.
- Do NOT trade multiple symbols in the same pilot session initially.
- Do NOT run the pilot without completing the preflight check.
- Do NOT leave MIS positions open overnight.
- Do NOT commit `.env` to git.
- Do NOT share your `ZERODHA_ACCESS_TOKEN` with anyone.
- Do NOT run the pilot from a machine on a dynamic IP that is not whitelisted.
- Do NOT ignore WARN items in the preflight output without understanding them.
- Do NOT retry a timed-out order without verifying via Kite that no duplicate exists.

---

## Escalation Path

If something goes wrong and you cannot resolve it:

1. Close all Kite positions manually (immediate priority).
2. Contact Zerodha support: support.zerodha.com (8:00–18:00 IST, Mon–Fri).
3. Have your Client ID, order IDs, and timestamps ready.
4. Document the incident per `docs/INCIDENT_RESPONSE.md`.
