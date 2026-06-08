# 📈 Python Quant Trading Engine

A fully automated, capital-constrained **Swing Trading Hedge Fund** for Indian Equities (NSE).

This repository was recently pivoted from an intraday scalping bot to a mathematically proven, multi-day swing trading engine.

---

## 🏛️ Architecture

The system runs completely hands-free via GitHub Actions. It is governed by a **Master Risk Engine** that acts as the portfolio manager.

**Capital Constraints:**
- **Maximum Portfolio Capital:** ₹2,00,000
- **Minimum Trade Size:** ₹50,000 per chunk
- **Margin Used:** 0x (Cash only)

### The Strategies
The engine continuously aggregates signals from three distinct swing trading strategies:
1. **MA Pullback Breakout**: Buys strong uptrending stocks during deep RSI panics.
2. **BB Squeeze Breakout**: Buys stocks consolidating in extremely tight Bollinger Bands right as they explode upwards.
3. **Black Swan Mean Reversion**: A long-only pairs trading strategy that buys historically correlated stocks when they violently diverge.

### The Master Engine
`scripts/run_master_trader.py` manages the entire portfolio:
- Calculates current free cash and locked capital.
- Gathers entry/exit signals from all 3 strategies.
- Dynamically allocates fractional capital (min ₹50k chunks).
- Brute-force rejects trades if the ₹2L cap is reached, protecting the account from over-allocation.
- Sends a unified end-of-day digest to Telegram.

---

## 🚀 How to Run

### 1. Backtest the Engine (5-Year Historical Simulation)
Simulates the exact ₹2 Lakh capital constraints against 5 years of daily market data, accurately proving how the bot rejects excess signals to protect capital.
```bash
python scripts/backtest_master_engine.py
```

### 2. Run the Daily Master Trader
Downloads today's market data, evaluates open positions, checks for exits, approves new entries based on free cash, and sends a Telegram digest.
```bash
python scripts/run_master_trader.py
```

---

## 📜 Legacy Intraday Engine
The original highly-complex Intraday MIS scalping engine (with Zerodha integration, live pilot runbooks, and microsecond parallelized validation) is preserved. For documentation on the older intraday architecture, please refer to:
[docs/LEGACY_INTRADAY_README.md](docs/LEGACY_INTRADAY_README.md)
