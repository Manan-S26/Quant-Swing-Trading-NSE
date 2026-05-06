"""Zerodha Kite Connect authentication manager.

Handles the three-step Zerodha auth flow:
  1. Redirect user to login URL.
  2. User approves → Zerodha redirects back with a request_token.
  3. Exchange request_token for a session access_token.

Design decisions:
  - All credentials are held as Pydantic SecretStr. Raw values are fetched
    only at the call site where the SDK requires them.
  - The KiteConnect client is injected — never instantiated here.
  - Secrets are never logged or included in repr.
  - This class does NOT place orders.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from pydantic import SecretStr

from trading_engine.common.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


class _SettingsLike(Protocol):
    """Structural type for anything that has the three Zerodha SecretStr fields."""

    zerodha_api_key: SecretStr
    zerodha_api_secret: SecretStr
    zerodha_access_token: SecretStr


class KiteAuthManager:
    """Manages Zerodha session credentials.

    Accepts any settings object that exposes the three Zerodha SecretStr
    fields (zerodha_api_key, zerodha_api_secret, zerodha_access_token) and
    a KiteConnect-compatible client.

    Usage:
        auth = KiteAuthManager(kite_client=kite, settings=settings)
        url = auth.get_login_url()
        # ...user logs in, you receive request_token via postback...
        auth.generate_session(request_token)
        assert auth.validate_token()
    """

    def __init__(self, kite_client: Any, settings: _SettingsLike) -> None:
        self._kite = kite_client
        self._api_key: SecretStr = settings.zerodha_api_key
        self._api_secret: SecretStr = settings.zerodha_api_secret
        # Access token: may already be set (from a previously stored session).
        self._access_token: SecretStr = settings.zerodha_access_token

    def __repr__(self) -> str:
        # Secrets must never appear in repr.
        return (
            f"KiteAuthManager("
            f"api_key_set={bool(self._api_key.get_secret_value())}, "
            f"token_valid={self.validate_token()})"
        )

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def get_login_url(self) -> str:
        """Return the Zerodha login URL for the configured API key.

        The user must visit this URL to approve the application and
        receive a request_token via the configured redirect/postback URL.
        """
        if not self._api_key.get_secret_value():
            raise ConfigurationError(
                "ZERODHA_API_KEY is not configured. "
                "Set it in .env before calling get_login_url()."
            )
        return self._kite.login_url()

    def generate_session(self, request_token: str) -> None:
        """Exchange a request_token for an access_token.

        Calls the injected Kite client's generate_session method, stores the
        resulting access_token internally as SecretStr, and sets it on the
        Kite client via set_access_token().

        The raw access_token is never logged.

        Raises:
            ConfigurationError: if api_key or api_secret is not configured.
            BrokerConnectionError: if the Zerodha API call fails.
        """
        if not self._api_key.get_secret_value():
            raise ConfigurationError("ZERODHA_API_KEY is not configured.")
        if not self._api_secret.get_secret_value():
            raise ConfigurationError("ZERODHA_API_SECRET is not configured.")
        if not request_token:
            raise ConfigurationError("request_token cannot be empty.")

        # Raw secret is extracted only at the SDK call boundary.
        data: dict[str, Any] = self._kite.generate_session(
            request_token,
            api_secret=self._api_secret.get_secret_value(),
        )
        raw_token: str = data.get("access_token", "")
        self._access_token = SecretStr(raw_token)
        self._kite.set_access_token(raw_token)
        # Log only that a session was established — never the token value.
        logger.info("Zerodha session generated. Access token set on Kite client.")

    def validate_token(self) -> bool:
        """Return True if an access_token is present and non-empty."""
        return bool(self._access_token.get_secret_value())

    def get_access_token_value(self) -> str:
        """Return the raw access token string.

        Use this only where the SDK requires a plain string, e.g.:
            kite.set_access_token(auth.get_access_token_value())

        Do NOT log or store this value in plain text.
        """
        return self._access_token.get_secret_value()
