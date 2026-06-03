"""Stateless Daily Paper Trader — Bollinger Band Squeeze Breakout.

Loads the best per-symbol params from reports/bb_squeeze_results.json,
fetches latest daily data from yfinance, replays all bars to reconstruct
strategy state, then checks if today's close triggered a signal.

Sends Telegram alerts on entry/exit signals.

Usage:
  python scripts/run_bb_squeeze_trader.py
  python scripts/run_bb_squeeze_trader.py --bot-token TOKEN --chat-id ID

Scheduled via GitHub Actions at 3:45 PM IST (9:45 UTC) Mon-Fri.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trading_engine.notifications.telegram import TelegramNotifier

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
_log = logging.getLogger(__name__)

REPORTS_DIR = ROOT / "reports"
BB_WINDOW = 20
BB_STD_MULT = 2.0
CAPITAL_PER_TRADE = 100_000

# The 14 OOS-passing symbols with their best params from the sweep
# Source: reports/bb_squeeze_results.json (pass_oos == true only)
def load_portfolio() -> list[dict]:
    path = REPORTS_DIR / "bb_squeeze_results.json"
    if not path.exists():
        _log.error("bb_squeeze_results.json not found. Run backtest_bb_squeeze.py first.")
        return []
    with open(path) as f:
        data = json.load(f)
    passing = [r for r in data["results"] if r["pass_oos"]]
    _log.info(f"Loaded {len(passing)} OOS-passing symbols from portfolio.")
    return passing


def fetch_data(symbol: str) -> pd.DataFrame | None:
    try:
        df = yf.download(f"{symbol}.NS", period="1y", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        df.index.name = "timestamp"
        df = df.reset_index()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        df = df.ffill().dropna(subset=["open", "high", "low", "close"])
        return df
    except Exception as exc:
        _log.warning(f"Failed to fetch {symbol}: {exc}")
        return None


def compute_bb(closes: np.ndarray, i: int) -> tuple[float, float, float]:
    """Return (middle, upper, lower) BB at index i using BB_WINDOW bars ending at i."""
    window = closes[i - BB_WINDOW + 1: i + 1]
    middle = float(np.mean(window))
    std = float(np.std(window, ddof=1))
    return middle, middle + BB_STD_MULT * std, middle - BB_STD_MULT * std


def run_strategy(df: pd.DataFrame, params: dict) -> dict:
    """
    Replay all bars to reconstruct current position state.
    Returns a dict describing today's signal (if any) and current position.
    """
    squeeze_threshold = params["squeeze_threshold"]
    stop_loss_pct = params["stop_loss_pct"]
    max_hold_days = params["max_hold_days"]

    closes = df["close"].values.astype(float)
    opens = df["open"].values.astype(float)
    lows = df["low"].values.astype(float)
    dates = df["timestamp"].values
    n = len(df)

    in_position = False
    qty = 0
    entry_price = 0.0
    entry_date = None
    stop_price = 0.0
    today_signal = None  # populated only on the last bar

    for i in range(BB_WINDOW, n):
        middle, upper, lower = compute_bb(closes, i)
        band_width = (upper - lower) / middle if middle > 0 else 999.0
        squeeze_now = band_width < squeeze_threshold
        close_i = float(closes[i])
        date_i = pd.Timestamp(dates[i])
        is_last = (i == n - 1)

        if in_position:
            days_held = (date_i - pd.Timestamp(entry_date)).days

            # Stop loss (intra-bar)
            if float(lows[i]) <= stop_price:
                exit_price = stop_price
                if is_last:
                    today_signal = {
                        "action": "EXIT",
                        "reason": "stop_loss",
                        "exit_price_approx": round(exit_price, 2),
                        "qty": qty,
                        "entry_price": round(entry_price, 2),
                        "pnl_approx": round((exit_price - entry_price) * qty, 2),
                    }
                in_position = False
                qty = 0
                entry_price = 0.0
                entry_date = None
                continue

            # Exit: below middle band or max hold
            if close_i < middle or days_held >= max_hold_days:
                reason = "below_middle_band" if close_i < middle else "max_hold_days"
                if is_last:
                    today_signal = {
                        "action": "EXIT",
                        "reason": reason,
                        "exit_price_approx": round(opens[i] if i + 1 < n else close_i, 2),
                        "qty": qty,
                        "entry_price": round(entry_price, 2),
                        "pnl_approx": round((close_i - entry_price) * qty, 2),
                    }
                in_position = False
                qty = 0
                entry_price = 0.0
                entry_date = None

        if not in_position:
            # Check previous bar squeeze
            prev_middle, prev_upper, prev_lower = compute_bb(closes, i - 1)
            prev_bw = (prev_upper - prev_lower) / prev_middle if prev_middle > 0 else 999.0
            prev_squeeze = prev_bw < squeeze_threshold

            if prev_squeeze and close_i > upper:
                # Signal: entry at tomorrow's open
                fill_price = float(opens[i]) if i + 1 >= n else float(opens[i + 1]) if not is_last else close_i
                qty = max(1, int(CAPITAL_PER_TRADE / fill_price))
                entry_price = fill_price
                entry_date = date_i
                stop_price = entry_price * (1 - stop_loss_pct / 100.0)
                in_position = True

                if is_last:
                    today_signal = {
                        "action": "ENTRY",
                        "reason": "bb_squeeze_breakout",
                        "entry_price_approx": round(fill_price, 2),
                        "qty": qty,
                        "stop_loss": round(stop_price, 2),
                        "capital_deployed": round(qty * fill_price, 0),
                    }

    return {
        "in_position": in_position,
        "signal": today_signal,
        "entry_price": round(entry_price, 2) if in_position else None,
        "entry_date": str(pd.Timestamp(entry_date).date()) if in_position and entry_date else None,
        "qty": qty if in_position else 0,
        "stop_price": round(stop_price, 2) if in_position else None,
        "last_close": round(float(closes[-1]), 2),
        "last_date": str(pd.Timestamp(dates[-1]).date()),
    }


def format_entry_msg(symbol: str, state: dict) -> str:
    sig = state["signal"]
    return (
        f"📈 BB SQUEEZE ENTRY — {symbol}\n"
        f"  Entry price : ₹{sig['entry_price_approx']:,}\n"
        f"  Qty         : {sig['qty']} shares\n"
        f"  Stop loss   : ₹{sig['stop_loss']:,}\n"
        f"  Capital     : ₹{sig['capital_deployed']:,.0f}\n"
        f"  Reason      : {sig['reason']}"
    )


def format_exit_msg(symbol: str, state: dict) -> str:
    sig = state["signal"]
    pnl = sig.get("pnl_approx", 0)
    sign = "+" if pnl >= 0 else ""
    emoji = "✅" if pnl >= 0 else "❌"
    return (
        f"{emoji} BB SQUEEZE EXIT — {symbol}\n"
        f"  Exit price  : ₹{sig['exit_price_approx']:,}\n"
        f"  Entry price : ₹{sig['entry_price']:,}\n"
        f"  Qty         : {sig['qty']} shares\n"
        f"  Est. PnL    : {sign}₹{pnl:,.0f}\n"
        f"  Reason      : {sig['reason']}"
    )


def run_paper_trader(bot_token: str, chat_id: str) -> None:
    notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)

    if bot_token and chat_id:
        notifier.send("🤖 BB Squeeze Paper Trader online — scanning signals...")
        _log.info("Telegram connected.")

    portfolio = load_portfolio()
    if not portfolio:
        return

    _log.info(f"Scanning {len(portfolio)} symbols...")
    signals_found = 0

    for entry in portfolio:
        symbol = entry["symbol"]
        params = entry["best_params"]

        df = fetch_data(symbol)
        if df is None or len(df) < BB_WINDOW + 2:
            _log.warning(f"[{symbol}] Insufficient data, skipping.")
            continue

        state = run_strategy(df, params)
        sig = state["signal"]

        if sig is None:
            _log.info(f"[{symbol}] No signal today. In position: {state['in_position']}")
            continue

        signals_found += 1
        if sig["action"] == "ENTRY":
            msg = format_entry_msg(symbol, state)
        else:
            msg = format_exit_msg(symbol, state)

        _log.info(f"[{symbol}] SIGNAL: {sig['action']} — {sig['reason']}")
        notifier.send(msg)

    if signals_found == 0:
        msg = "✅ BB Squeeze scan complete. No signals today."
        _log.info(msg)
        notifier.send(msg)
    else:
        _log.info(f"Scan complete. {signals_found} signal(s) sent.")


if __name__ == "__main__":
    import argparse
    load_dotenv()

    parser = argparse.ArgumentParser(description="BB Squeeze daily paper trader.")
    parser.add_argument("--bot-token", default=os.getenv("TELEGRAM_BOT_TOKEN", ""))
    parser.add_argument("--chat-id", default=os.getenv("TELEGRAM_CHAT_ID", ""))
    args = parser.parse_args()

    run_paper_trader(args.bot_token, args.chat_id)
