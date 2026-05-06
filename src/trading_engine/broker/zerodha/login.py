"""Zerodha login helper — reusable logic for generating daily access tokens.

Keeps the login script thin by providing all credential-handling here.
Secrets are never logged. API secret is never printed.

No KiteConnect import at module level — the Kite client is injected.
No live order placement.  Read-only auth flow only.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from trading_engine.broker.zerodha.auth import KiteAuthManager
from trading_engine.common.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Login URL
# ---------------------------------------------------------------------------


def get_login_url(settings: Any, kite_client: Any) -> str:
    """Return the Zerodha login URL for the configured API key.

    Args:
        settings:    Settings object with zerodha_api_key SecretStr field.
        kite_client: Injected KiteConnect-compatible client.

    Returns:
        Login URL string.

    Raises:
        ConfigurationError: if ZERODHA_API_KEY is not set.
    """
    auth = KiteAuthManager(kite_client=kite_client, settings=settings)
    return auth.get_login_url()


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------


def exchange_request_token(
    settings: Any,
    kite_client: Any,
    request_token: str,
) -> str:
    """Exchange a Zerodha request_token for an access_token.

    Args:
        settings:      Settings object with zerodha_api_key / api_secret fields.
        kite_client:   Injected KiteConnect-compatible client.
        request_token: Token received from the Zerodha redirect URL.

    Returns:
        Raw access token string.  Do NOT log or store in plain text.

    Raises:
        ConfigurationError: if credentials are missing or request_token is empty.
    """
    if not request_token or not request_token.strip():
        raise ConfigurationError("request_token cannot be empty.")

    auth = KiteAuthManager(kite_client=kite_client, settings=settings)
    auth.generate_session(request_token.strip())
    return auth.get_access_token_value()


# ---------------------------------------------------------------------------
# .env file updater (optional --write-env)
# ---------------------------------------------------------------------------


def update_env_file(env_path: str | Path, access_token: str) -> None:
    """Update ZERODHA_ACCESS_TOKEN in a .env file.

    Finds the ZERODHA_ACCESS_TOKEN= line and replaces it.  If the line does
    not exist, appends it.

    Safety:
      - Never logs the token value.
      - Never touches other lines.
      - The caller must ensure the file path is correct.

    Args:
        env_path:     Path to the .env file.
        access_token: The new access token (raw string — handle carefully).

    Raises:
        FileNotFoundError: if the .env file does not exist.
    """
    path = Path(env_path)
    if not path.exists():
        raise FileNotFoundError(f".env file not found: {path}")

    content = path.read_text(encoding="utf-8")
    pattern = re.compile(r"^(ZERODHA_ACCESS_TOKEN\s*=\s*).*$", re.MULTILINE)

    new_line = f"ZERODHA_ACCESS_TOKEN={access_token}"
    if pattern.search(content):
        updated = pattern.sub(new_line, content)
    else:
        updated = content.rstrip() + f"\n{new_line}\n"

    path.write_text(updated, encoding="utf-8")
    logger.info("Updated ZERODHA_ACCESS_TOKEN in %s (token value not logged).", path)


# ---------------------------------------------------------------------------
# Credential validator
# ---------------------------------------------------------------------------


def validate_credentials(settings: Any) -> list[str]:
    """Return a list of missing credential names.

    Args:
        settings: Settings object with zerodha_api_key and zerodha_api_secret.

    Returns:
        List of missing field names.  Empty list means credentials are present.
    """
    missing: list[str] = []
    for attr in ("zerodha_api_key", "zerodha_api_secret"):
        val = getattr(settings, attr, None)
        raw = val.get_secret_value() if val is not None else ""
        if not raw or raw in ("replace_me", ""):
            missing.append(attr.upper())
    return missing
