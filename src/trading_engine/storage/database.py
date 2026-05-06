"""Database connection scaffolding using SQLAlchemy.

This module provides:
  - Base declarative model for future table definitions
  - Engine initialisation
  - A session context manager
  - A health check function

The full schema (orders, trades, positions, etc.) will be added in later
milestones. This file only establishes the connection plumbing.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)

# Singleton engine and session factory — initialised once at startup.
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


class Base(DeclarativeBase):
    """Declarative base for all ORM models.

    Import and subclass this in each storage model module:
        from trading_engine.storage.database import Base
        class MyModel(Base): ...
    """


def init_db(database_url: str) -> Engine:
    """Initialise the SQLAlchemy engine and session factory.

    Call once at application startup, passing the DATABASE_URL from Settings.
    pool_pre_ping=True ensures stale connections are recycled automatically.
    """
    global _engine, _SessionLocal
    _engine = create_engine(database_url, pool_pre_ping=True)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    # Log without exposing the URL (it may contain credentials).
    logger.info("Database engine initialised")
    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Yield a database session with automatic commit/rollback.

    Usage:
        with get_session() as session:
            session.add(record)
    """
    if _SessionLocal is None:
        raise RuntimeError(
            "Database not initialised. Call init_db(database_url) first."
        )
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def health_check(engine: Engine | None = None) -> bool:
    """Return True if the database is reachable.

    Pass an explicit engine to test a specific connection, or leave None
    to use the module-level engine initialised by init_db().
    """
    target = engine or _engine
    if target is None:
        logger.warning("Database health check failed: engine not initialised")
        return False
    try:
        with target.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        return False
