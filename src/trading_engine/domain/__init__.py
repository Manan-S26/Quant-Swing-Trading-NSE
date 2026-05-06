"""Domain package — broker-independent models, enums, and identifiers.

This package contains the shared vocabulary of the trading engine:
  - enums.py   : canonical enumerations (Side, OrderType, OrderStatus, ...)
  - models.py  : Pydantic v2 domain models (RiskDecision, InternalOrder, ...)
  - identifiers.py : ID generation helpers

Nothing in this package imports Zerodha SDK, SQLAlchemy, or broker-specific code.
"""

from __future__ import annotations
