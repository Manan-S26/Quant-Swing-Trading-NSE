"""Tests for universe configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_engine.data.universe import UniverseConfig, load_universe_config
from trading_engine.domain.enums import Exchange


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_universe_yaml(tmp_path: Path) -> Path:
    content = """
universe:
  name: test_universe
  exchange: NSE
  symbols:
    - RELIANCE
    - HDFCBANK
    - INFY
  filters:
    min_avg_daily_value: 100000000
"""
    p = tmp_path / "test_config.yaml"
    p.write_text(content)
    return p


@pytest.fixture
def minimal_universe_yaml(tmp_path: Path) -> Path:
    content = """
universe:
  name: minimal
  symbols:
    - TCS
"""
    p = tmp_path / "minimal.yaml"
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# load_universe_config
# ---------------------------------------------------------------------------

class TestLoadUniverseConfig:
    def test_loads_valid_yaml(self, valid_universe_yaml: Path) -> None:
        config = load_universe_config(valid_universe_yaml)
        assert config.name == "test_universe"
        assert config.exchange == Exchange.NSE
        assert "RELIANCE" in config.symbols

    def test_loads_symbols_correctly(self, valid_universe_yaml: Path) -> None:
        config = load_universe_config(valid_universe_yaml)
        assert config.symbols == ["RELIANCE", "HDFCBANK", "INFY"]

    def test_loads_filters(self, valid_universe_yaml: Path) -> None:
        config = load_universe_config(valid_universe_yaml)
        assert config.filters["min_avg_daily_value"] == 100000000

    def test_minimal_config_defaults_exchange_to_nse(
        self, minimal_universe_yaml: Path
    ) -> None:
        config = load_universe_config(minimal_universe_yaml)
        assert config.exchange == Exchange.NSE

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_universe_config(tmp_path / "nonexistent.yaml")

    def test_missing_universe_section_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "no_universe.yaml"
        p.write_text("app:\n  env: development\n")
        with pytest.raises(ValueError, match="universe"):
            load_universe_config(p)

    def test_loads_default_yaml(self) -> None:
        """The repo's default.yaml must be loadable."""
        config = load_universe_config("configs/default.yaml")
        assert len(config.symbols) >= 5
        assert config.exchange == Exchange.NSE

    def test_default_yaml_has_ten_symbols(self) -> None:
        config = load_universe_config("configs/default.yaml")
        assert len(config.symbols) == 10


# ---------------------------------------------------------------------------
# UniverseConfig validation
# ---------------------------------------------------------------------------

class TestUniverseConfigValidation:
    def test_valid_config(self) -> None:
        config = UniverseConfig(name="test", symbols=["RELIANCE", "INFY"])
        assert len(config.symbols) == 2

    def test_get_symbols(self) -> None:
        config = UniverseConfig(name="test", symbols=["RELIANCE", "INFY", "TCS"])
        assert config.get_symbols() == ["RELIANCE", "INFY", "TCS"]

    def test_get_symbols_returns_copy(self) -> None:
        config = UniverseConfig(name="test", symbols=["RELIANCE"])
        syms = config.get_symbols()
        syms.append("HDFCBANK")
        assert config.symbols == ["RELIANCE"]

    def test_empty_name_raises(self) -> None:
        with pytest.raises(ValidationError, match="name"):
            UniverseConfig(name="", symbols=["RELIANCE"])

    def test_whitespace_name_raises(self) -> None:
        with pytest.raises(ValidationError, match="name"):
            UniverseConfig(name="   ", symbols=["RELIANCE"])

    def test_empty_symbols_list_raises(self) -> None:
        with pytest.raises(ValidationError, match="symbols"):
            UniverseConfig(name="test", symbols=[])

    def test_duplicate_symbols_raises(self) -> None:
        with pytest.raises(ValidationError, match="unique"):
            UniverseConfig(name="test", symbols=["RELIANCE", "INFY", "RELIANCE"])

    def test_empty_string_in_symbols_raises(self) -> None:
        with pytest.raises(ValidationError, match="empty"):
            UniverseConfig(name="test", symbols=["RELIANCE", "", "INFY"])

    def test_default_exchange_is_nse(self) -> None:
        config = UniverseConfig(name="test", symbols=["RELIANCE"])
        assert config.exchange == Exchange.NSE

    def test_filters_default_empty(self) -> None:
        config = UniverseConfig(name="test", symbols=["RELIANCE"])
        assert config.filters == {}

    def test_custom_filters_stored(self) -> None:
        config = UniverseConfig(
            name="test",
            symbols=["RELIANCE"],
            filters={"min_volume": 1000000},
        )
        assert config.filters["min_volume"] == 1000000
