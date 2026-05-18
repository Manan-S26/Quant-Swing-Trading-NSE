# Operating Checklist — Live Order Pilot

**Version:** Milestone 17
**Scope:** NSE cash equities, Zerodha Kite Connect, intraday MIS only
**Purpose:** Steps to follow before, during, and after any live pilot order session.

> **Rule:** If any item is unclear or fails, stop and investigate before proceeding.

---

## 1. Pre-Market Checklist (Before Market Opens — by 09:00 IST)

- [ ] Machine is running. Do not attempt pilot from an unstable machine.
- [ ] Internet connection is stable. Prefer wired over WiFi.
- [ ] Static IP is active and matches the IP whitelisted in Zerodha Kite Connect.
- [ ] System clock is synced (NTP). Check with: `timedatectl` or `date`.
- [ ] Project code is up to date: `git pull && git status` (no dirty working tree).
- [ ] All tests pass: `python3 -m pytest -q` — must show 0 failures.
- [ ] Ruff lint passes: `python3 -m ruff check src tests scripts`.
- [ ] Python virtualenv is activated.

---

## 2. Credential and Token Checklist

- [ ] `ZERODHA_API_KEY` is set in `.env` (not empty).
- [ ] `ZERODHA_API_SECRET` is set in `.env` (not empty).
- [ ] `ZERODHA_ACCESS_TOKEN` has been freshly generated today using `scripts/zerodha_login_helper.py`.
  - Kite access tokens expire daily. Yesterday's token is invalid.
- [ ] Token has been tested: `python3 scripts/download_zerodha_historical.py --dry-run` exits 0.
- [ ] `.env` file is never committed to git. Verify: `git status` shows `.env` as untracked/ignored.

---

## 3. Static IP Note

> Zerodha requires API requests to originate from a whitelisted static IP address.
> Without a matching static IP, all API calls will be rejected (401 Unauthorized).

- [ ] Confirm your public IP matches the IP registered in Kite Connect app settings.
- [ ] Check public IP: `curl -s https://api.ipify.org` (or `curl -s ifconfig.me`).
- [ ] If IP does not match, do NOT proceed. Update the whitelist in Kite Connect and wait for propagation.
- [ ] Cloud/VPS users: confirm Elastic IP or equivalent is assigned.
- [ ] Home users: contact ISP for a static IP, or use a VPN/proxy only if its IP is whitelisted.

---

## 4. Config Checklist

- [ ] `APP_ENV` is set appropriately (`production` for live).
- [ ] `LIVE_TRADING_ENABLED=true` (required for pilot).
- [ ] `LIVE_ORDER_EXECUTION_ENABLED=true` (required for pilot).
- [ ] `LIVE_ORDER_PILOT_ENABLED=true` (required for pilot).
- [ ] `LIVE_MAX_ORDER_QUANTITY` is set to `1` for first pilot run.
- [ ] `LIVE_ALLOWED_SYMBOLS` contains exactly the symbol(s) you intend to trade (JSON array).
- [ ] `LIVE_ALLOWED_EXCHANGE=NSE`.
- [ ] `LIVE_ALLOWED_PRODUCT=MIS` (intraday only — will auto-close at 3:20 IST).
- [ ] `LIVE_ALLOWED_ORDER_TYPES` set to `["MARKET"]` for first run (LIMIT adds complexity).
- [ ] `GLOBAL_KILL_SWITCH=false` (or unset). Kill switch must be inactive.
- [ ] All defaults reviewed: run `python3 scripts/live_pilot_preflight.py` and confirm all required checks PASS.

---

## 5. Risk Limit Checklist

- [ ] `MAX_DAILY_LOSS` is set to an amount you are willing to lose today (e.g. 500).
- [ ] `MAX_ORDER_VALUE` is set to a value appropriate for 1-share pilot (e.g. 5000).
- [ ] `MAX_OPEN_POSITIONS` is set to 1 for first pilot.
- [ ] `MAX_TRADES_PER_DAY` is set to 2–5 for first pilot.
- [ ] `MAX_ORDERS_PER_SECOND` is set to 1.
- [ ] Risk limits have been reviewed against current account balance.
- [ ] You can afford to lose `MAX_DAILY_LOSS` today without financial hardship.

---

## 6. Symbol Universe Checklist

- [ ] Pilot symbol is a large-cap, liquid NSE equity (e.g. RELIANCE, INFY, TCS).
- [ ] Symbol spelling matches Zerodha's exact `tradingsymbol` (e.g. `RELIANCE`, not `RELIANCE.NSE`).
- [ ] Symbol has sufficient intraday liquidity (check bid/ask spread pre-market).
- [ ] No corporate actions (bonus, split, ex-dividend) scheduled today for the symbol.
- [ ] Symbol is not circuit-locked or suspended.

---

## 7. Dashboard Checklist (if using)

- [ ] Dashboard path (`data/dashboard/session_status.json`) is writable.
- [ ] Dashboard app is running if monitoring via Streamlit: `make run-dashboard`.
- [ ] Session file from previous runs has been cleared or is stale (check `generated_at` timestamp).

---

## 8. Dry-Run Checklist (Run BEFORE any real order)

Run the dry-run for your intended order and verify the output:

```bash
python3 scripts/live_order_dry_run.py \
  --symbol RELIANCE \
  --side BUY \
  --quantity 1 \
  --order-type MARKET
```

- [ ] Dry-run exits with code 0.
- [ ] JSON output shows `approval_status: "approved"`.
- [ ] `message` field contains "DRY RUN".
- [ ] `estimated_order_value` is within your risk limits.
- [ ] No errors or exceptions in output.

---

## 9. Preflight Checklist

```bash
python3 scripts/live_pilot_preflight.py
```

- [ ] All **REQUIRED** checks show **PASS**.
- [ ] No **FAIL** items in the required section.
- [ ] Review any **WARN** items and decide if they are acceptable.
- [ ] If `--require-static-ip-confirmed` is used, confirm that check also passes.

---

## 10. Manual Pilot Order Checklist

```bash
python3 scripts/live_order_pilot.py \
  --symbol RELIANCE \
  --side BUY \
  --quantity 1 \
  --order-type MARKET \
  --i-understand-this-places-real-orders
```

- [ ] Script prompts for confirmation phrase.
- [ ] Type exactly: `PLACE LIVE ORDER`
- [ ] Script outputs JSON with `success: true` and a `broker_order_id`.
- [ ] Note the `broker_order_id` for reconciliation.
- [ ] Log the time, symbol, side, quantity, and broker_order_id in your trading journal.

---

## 11. Post-Trade Reconciliation Checklist

Immediately after order placement:

- [ ] Open Kite web app or mobile app and verify the order appears under "Orders".
- [ ] Verify order status (OPEN, COMPLETE, REJECTED).
- [ ] If REJECTED: note the rejection reason. Do not retry without investigating.
- [ ] If COMPLETE: verify fill price and quantity match intent.
- [ ] Run reconciliation script if available, or manually compare ledger vs. broker.
- [ ] Check that audit log was written: `tail -5 data/audit/pilot_orders.jsonl`.
- [ ] Verify no duplicate orders were placed.

---

## 12. End-of-Day Shutdown Checklist (Before 15:20 IST)

- [ ] All open MIS positions are closed. Zerodha auto-closes MIS at ~15:20 IST, but verify manually.
- [ ] No open intraday orders remain. Cancel any open orders in Kite.
- [ ] Final P&L reviewed in Kite.
- [ ] Kill switch activated if ending session: set `GLOBAL_KILL_SWITCH=true`.
- [ ] Pilot flags disabled for safety: set `LIVE_ORDER_EXECUTION_ENABLED=false` and `LIVE_ORDER_PILOT_ENABLED=false`.
- [ ] Access token will expire at midnight — no action needed unless running overnight (do not run overnight).
- [ ] Audit log backed up if desired: `cp data/audit/pilot_orders.jsonl data/audit/pilot_orders_$(date +%Y%m%d).jsonl`.
- [ ] Trading journal updated with results.

---

## Quick Reference: Script Safety Properties

| Script | Places Real Orders | Requires Credentials | Requires Safety Flag |
|---|---|---|---|
| `live_order_dry_run.py` | No | No | No |
| `live_pilot_preflight.py` | No | No (checks presence) | No |
| `run_paper_live_zerodha.py` | No | Yes (market data) | `--i-understand-this-uses-live-market-data` |
| `live_order_pilot.py` | **YES** | **YES** | `--i-understand-this-places-real-orders` + phrase |
| `download_zerodha_historical.py` | No | Yes (read-only) | No |
