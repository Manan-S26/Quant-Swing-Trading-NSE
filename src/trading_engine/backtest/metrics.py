"""Backtest performance metrics.

Calculates summary statistics from a completed backtest run.
All calculations are defensive against edge cases (no trades, zero denominators).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from trading_engine.domain.enums import Side
from trading_engine.domain.models import TradeFill

_ZERO = Decimal("0")


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


def calculate_backtest_metrics(
    initial_cash: Decimal,
    final_equity: Decimal,
    equity_curve: Sequence[tuple[object, Decimal]],
    fills: Sequence[TradeFill],
) -> BacktestMetrics:
    """Compute BacktestMetrics from a completed run.

    Args:
        initial_cash:  Starting portfolio cash.
        final_equity:  Ending portfolio equity.
        equity_curve:  List of (timestamp, equity) pairs in order.
        fills:         All TradeFill objects from the run.

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
