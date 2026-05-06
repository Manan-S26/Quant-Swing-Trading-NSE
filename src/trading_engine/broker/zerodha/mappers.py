"""Zerodha response → internal model mappers.

This module will contain functions that convert raw Zerodha API dictionaries
into the engine's internal domain models (Instrument, Position, TradeFill, etc.).

Deferred to a later milestone.  Currently a placeholder.

Future functions:
    zerodha_instrument_to_internal(raw: dict) -> Instrument
    zerodha_position_to_internal(raw: dict) -> Position
    zerodha_order_to_internal(raw: dict) -> InternalOrder
    zerodha_trade_to_internal(raw: dict) -> TradeFill
"""

from __future__ import annotations
