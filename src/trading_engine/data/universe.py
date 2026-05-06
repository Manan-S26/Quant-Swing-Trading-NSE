"""Instrument universe configuration.

The universe defines which symbols the engine is allowed to trade,
download data for, and run strategies against.

Loading:
    config = load_universe_config("configs/default.yaml")
    symbols = config.get_symbols()   # ["RELIANCE", "HDFCBANK", ...]

The YAML file must have a top-level "universe" section:

    universe:
      name: nifty50_starter
      exchange: NSE
      symbols:
        - RELIANCE
        - HDFCBANK
      filters:
        min_avg_daily_value: 100000000
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from trading_engine.domain.enums import Exchange


class UniverseConfig(BaseModel):
    """Configuration for the tradable instrument universe."""

    name: str
    exchange: Exchange = Exchange.NSE
    symbols: list[str]
    filters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("universe name cannot be empty")
        return v

    @field_validator("symbols")
    @classmethod
    def symbols_valid(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("universe symbols list cannot be empty")
        for sym in v:
            if not sym or not sym.strip():
                raise ValueError(f"universe symbols cannot contain empty strings, got {v!r}")
        if len(v) != len(set(v)):
            seen: set[str] = set()
            dupes = [s for s in v if s in seen or seen.add(s)]  # type: ignore[func-returns-value]
            raise ValueError(f"universe symbols must be unique, duplicates: {dupes}")
        return v

    def get_symbols(self) -> list[str]:
        """Return the list of tradable symbols."""
        return list(self.symbols)


def load_universe_config(config_path: str | Path) -> UniverseConfig:
    """Load universe configuration from a YAML file.

    The file must contain a top-level "universe" section. Additional
    sections (app, risk, costs, etc.) are ignored.

    Args:
        config_path: Path to the YAML config file.

    Returns:
        UniverseConfig with validated fields.

    Raises:
        FileNotFoundError: if the config file does not exist.
        ValueError: if the "universe" section is missing or invalid.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = yaml.safe_load(path.read_text()) or {}
    universe_section = raw.get("universe")
    if not universe_section:
        raise ValueError(f"Config file {path} is missing a 'universe' section.")

    return UniverseConfig(**universe_section)
