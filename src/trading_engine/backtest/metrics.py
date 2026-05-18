"""Backtest performance metrics.

Calculates summary statistics from a completed backtest run.
All calculations are defensive against edge cases (no trades, zero denominators).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_engine.domain.enums import Side
from trading_engine.domain.models import TradeFill

_ZERO = Decimal("0")
_TRADING_DAYS_PER_YEAR = 252


@dataclass
class BacktestMetrics:
    """Summary metrics for a completed backtest."""

    total_return: Decimal = _ZERO  # (final_equity - initial_cash) / initial_cash
    total_pnl: Decimal = _ZERO  # final_equity - initial_cash
    realized_pnl: Decimal = _ZERO
    unrealized_pnl: Decimal = _ZERO
    max_drawdown: Decimal = _ZERO  # Peak-to-trough as fraction
    win_rate: Decimal = _ZERO  # Fraction of winning trades
    profit_factor: Decimal = _ZERO  # Gross profit / gross loss
    trade_count: int = 0  # Number of fills
    winning_trades: int = 0
    losing_trades: int = 0
    average_win: Decimal = _ZERO
    average_loss: Decimal = _ZERO  # Absolute value
    expectancy: Decimal = _ZERO  # Expected P&L per trade
    total_fees: Decimal = _ZERO
    # New fields (Milestone 13)
    average_trade_pnl: Decimal = _ZERO
    best_trade_pnl: Decimal = _ZERO
    worst_trade_pnl: Decimal = _ZERO
    sharpe_ratio: float | None = None  # annualised; None when insufficient data
    sortino_ratio: float | None = None  # annualised; None when insufficient data
    cagr: float | None = None  # compound annual growth rate; None when period < 1 day


def calculate_backtest_metrics(
    initial_cash: Decimal,
    final_equity: Decimal,
    equity_curve: Sequence[tuple[object, Decimal]],
    fills: Sequence[TradeFill],
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> BacktestMetrics:
    """Compute BacktestMetrics from a completed run.

    Args:
        initial_cash:  Starting portfolio cash.
        final_equity:  Ending portfolio equity.
        equity_curve:  List of (timestamp, equity) pairs in order.
        fills:         All TradeFill objects from the run.
        start_time:    First bar timestamp (for CAGR).
        end_time:      Last bar timestamp (for CAGR).

    Returns:
        Populated BacktestMetrics.
    """
    metrics = BacktestMetrics()

    total_pnl = final_equity - initial_cash
    metrics.total_pnl = total_pnl
    metrics.total_return = total_pnl / initial_cash if initial_cash != _ZERO else _ZERO

    # Fees
    metrics.total_fees = sum((f.fees for f in fills), _ZERO)

    # Trade count
    metrics.trade_count = len(fills)

    # Max drawdown from equity curve
    if equity_curve:
        equities = [e for _, e in equity_curve]
        peak = equities[0]
        max_dd = _ZERO
        for eq in equities:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > _ZERO else _ZERO
            if dd > max_dd:
                max_dd = dd
        metrics.max_drawdown = max_dd

    # Per-trade P&L: pair BUY and SELL fills by symbol (FIFO simplified).
    # For v1, we measure realized P&L per SELL fill using a simple running
    # average cost approach per symbol.
    buy_queue: dict[str, list[tuple[int, Decimal]]] = {}  # symbol → [(qty, price)]
    trade_pnls: list[Decimal] = []

    for fill in fills:
        sym = fill.symbol
        if fill.side == Side.BUY:
            buy_queue.setdefault(sym, []).append((fill.quantity, fill.price))
        elif fill.side == Side.SELL:
            cost_basis = _compute_cost_basis(buy_queue.get(sym, []), fill.quantity)
            gross = Decimal(str(fill.quantity)) * fill.price
            pnl = gross - cost_basis - fill.fees
            trade_pnls.append(pnl)

    wins = [p for p in trade_pnls if p > _ZERO]
    losses = [p for p in trade_pnls if p < _ZERO]

    metrics.winning_trades = len(wins)
    metrics.losing_trades = len(losses)
    metrics.realized_pnl = sum(trade_pnls, _ZERO)

    total_evaluated = len(trade_pnls)
    metrics.win_rate = (
        Decimal(str(len(wins))) / Decimal(str(total_evaluated)) if total_evaluated > 0 else _ZERO
    )

    gross_profit = sum(wins, _ZERO)
    gross_loss = abs(sum(losses, _ZERO))

    metrics.profit_factor = gross_profit / gross_loss if gross_loss > _ZERO else _ZERO

    metrics.average_win = gross_profit / Decimal(str(len(wins))) if wins else _ZERO
    metrics.average_loss = gross_loss / Decimal(str(len(losses))) if losses else _ZERO

    # Expectancy = (win_rate × avg_win) - (loss_rate × avg_loss)
    loss_rate = Decimal("1") - metrics.win_rate
    metrics.expectancy = metrics.win_rate * metrics.average_win - loss_rate * metrics.average_loss

    # Per-trade summary stats
    if trade_pnls:
        metrics.average_trade_pnl = sum(trade_pnls, _ZERO) / Decimal(str(len(trade_pnls)))
        metrics.best_trade_pnl = max(trade_pnls)
        metrics.worst_trade_pnl = min(trade_pnls)

    # Sharpe and Sortino from equity curve returns
    metrics.sharpe_ratio, metrics.sortino_ratio = _compute_risk_ratios(equity_curve)

    # CAGR
    metrics.cagr = _compute_cagr(
        initial_cash=initial_cash,
        final_equity=final_equity,
        start_time=start_time,
        end_time=end_time,
    )

    return metrics


def _compute_cost_basis(buy_queue: list[tuple[int, Decimal]], sell_qty: int) -> Decimal:
    """FIFO cost basis for a given sell quantity."""
    remaining = sell_qty
    cost = _ZERO
    for qty, price in buy_queue:
        if remaining <= 0:
            break
        used = min(qty, remaining)
        cost += Decimal(str(used)) * price
        remaining -= used
    return cost


def _compute_risk_ratios(
    equity_curve: Sequence[tuple[object, Decimal]],
) -> tuple[float | None, float | None]:
    """Compute annualised Sharpe and Sortino ratios from an equity curve.

    Returns (sharpe, sortino); both None when fewer than 2 data points.
    Assumes bar-to-bar returns; annualises using sqrt(252).
    """
    equities = [float(e) for _, e in equity_curve]
    if len(equities) < 2:
        return None, None

    returns: list[float] = []
    for i in range(1, len(equities)):
        prev = equities[i - 1]
        if prev == 0.0:
            returns.append(0.0)
        else:
            returns.append((equities[i] - prev) / prev)

    n = len(returns)
    if n < 2:
        return None, None

    mean_r = sum(returns) / n
    variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
    std_dev = math.sqrt(variance) if variance > 0 else 0.0

    ann_factor = math.sqrt(_TRADING_DAYS_PER_YEAR)
    sharpe = (mean_r / std_dev * ann_factor) if std_dev > 0 else None

    # Sortino: downside deviation only
    downside_returns = [r for r in returns if r < 0]
    if downside_returns:
        downside_var = sum(r**2 for r in downside_returns) / (n - 1)
        downside_std = math.sqrt(downside_var)
        sortino = (mean_r / downside_std * ann_factor) if downside_std > 0 else None
    else:
        sortino = None  # No losing periods — undefined (infinite)

    return sharpe, sortino


def _compute_cagr(
    initial_cash: Decimal,
    final_equity: Decimal,
    start_time: datetime | None,
    end_time: datetime | None,
) -> float | None:
    """Compute CAGR given start/end equity and timestamps.

    Returns None if:
    - start_time or end_time is None
    - period is less than 1 day
    - initial_cash is zero
    """
    if start_time is None or end_time is None:
        return None
    if initial_cash <= _ZERO:
        return None

    delta = end_time - start_time
    days = delta.total_seconds() / 86400.0
    if days < 1.0:
        return None

    years = days / 365.25
    ratio = float(final_equity) / float(initial_cash)
    if ratio <= 0:
        return None

    try:
        return ratio ** (1.0 / years) - 1.0
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
