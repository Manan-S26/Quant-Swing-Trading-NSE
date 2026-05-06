"""Configuration management using Pydantic Settings.

Settings are loaded from environment variables and an optional .env file.
Sensitive fields (API keys, secrets, tokens) use SecretStr so they are never
accidentally logged or printed.

Safe defaults: LIVE_TRADING_ENABLED is always False unless explicitly set.
"""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # Application
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")

    # Database
    database_url: str = Field(
        default="postgresql+psycopg://trading:trading@localhost:5432/trading_engine"
    )

    # Zerodha credentials — stored as SecretStr to prevent accidental logging
    zerodha_api_key: SecretStr = Field(default="")
    zerodha_api_secret: SecretStr = Field(default="")
    zerodha_access_token: SecretStr = Field(default="")

    # Trading mode flags — defaults must be safe
    live_trading_enabled: bool = Field(default=False)
    paper_trading_enabled: bool = Field(default=True)

    # Risk limits
    max_daily_loss: float = Field(default=1000.0, gt=0)
    max_order_value: float = Field(default=10000.0, gt=0)
    max_trades_per_day: int = Field(default=20, gt=0)
    order_rate_limit_per_second: int = Field(default=1, gt=0)

    # Data paths and historical download defaults
    data_dir: str = Field(default="./data")
    historical_interval: str = Field(default="5minute")
    historical_from_date: str = Field(default="")
    historical_to_date: str = Field(default="")

    def __repr__(self) -> str:
        # Secrets are intentionally excluded from repr and str.
        return (
            f"Settings("
            f"app_env={self.app_env!r}, "
            f"log_level={self.log_level!r}, "
            f"live_trading_enabled={self.live_trading_enabled}, "
            f"paper_trading_enabled={self.paper_trading_enabled})"
        )

    def __str__(self) -> str:
        return self.__repr__()


def load_settings(**overrides: object) -> Settings:
    """Load settings from environment variables, .env file, and optional overrides.

    Overrides take precedence over environment variables and the .env file.
    Use this factory in application startup code.
    """
    return Settings(**overrides)  # type: ignore[arg-type]
