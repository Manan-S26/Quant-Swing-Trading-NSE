"""Generate a Zerodha daily access token interactively.

Zerodha access tokens expire after each trading day. This script guides the
user through the three-step OAuth-like flow:
  1. Visit the Zerodha login URL.
  2. Approve the app and copy the request_token from the redirect URL.
  3. This script exchanges the request_token for an access_token.

The access token is printed but never logged.  Use --write-env to
automatically update ZERODHA_ACCESS_TOKEN in your .env file.

Usage:
  python3 scripts/zerodha_login_helper.py

  # Update .env automatically (careful — never commit .env):
  python3 scripts/zerodha_login_helper.py --write-env

Safety:
  - API secret is never printed.
  - Access token is printed only for the user to copy; it is never logged.
  - .env is updated only when --write-env is explicitly passed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trading_engine.broker.zerodha.login import (  # noqa: E402
    exchange_request_token,
    get_login_url,
    update_env_file,
    validate_credentials,
)
from trading_engine.common.config import load_settings  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a Zerodha access token interactively.")
    parser.add_argument(
        "--write-env",
        action="store_true",
        help="Update ZERODHA_ACCESS_TOKEN in .env (never commits or logs secrets)",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to the .env file to update (default: .env)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, kite_client: object | None = None) -> int:
    """Entry point.  kite_client can be injected for testing."""
    args = _parse_args(argv)
    settings = load_settings()

    # Validate that API key and secret are configured.
    missing = validate_credentials(settings)
    if missing:
        print(
            f"\n[ERROR] Missing credentials: {missing}\n"
            "Set ZERODHA_API_KEY and ZERODHA_API_SECRET in your .env file.\n"
            "Do NOT set ZERODHA_ACCESS_TOKEN here — this script generates it.\n"
        )
        return 1

    # Build Kite client if not injected (production path).
    if kite_client is None:
        try:
            from kiteconnect import KiteConnect  # type: ignore[import]
        except ImportError:
            print(
                "[ERROR] kiteconnect package is not installed.\n"
                "Install it with: pip install kiteconnect\n"
            )
            return 1
        kite_client = KiteConnect(api_key=settings.zerodha_api_key.get_secret_value())

    # Step 1 — print login URL.
    try:
        url = get_login_url(settings, kite_client)
    except Exception as exc:
        print(f"[ERROR] Could not build login URL: {exc}")
        return 1

    print("\n=== Zerodha Login Helper ===")
    print("\nStep 1: Open this URL in your browser and log in:")
    print(f"\n  {url}\n")
    print("Step 2: After approving, Zerodha will redirect you to your configured")
    print("        redirect URL.  Copy the 'request_token' parameter from the URL.")
    print("        It looks like: https://your-redirect/?request_token=XXXXX&...\n")

    # Step 3 — collect request_token from user.
    try:
        request_token = input("Paste the request_token here: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return 1

    if not request_token:
        print("[ERROR] No request_token provided. Aborted.")
        return 1

    # Step 4 — exchange for access token.
    try:
        access_token = exchange_request_token(settings, kite_client, request_token)
    except Exception as exc:
        print(f"\n[ERROR] Failed to generate session: {exc}")
        return 1

    # Print instructions — show the token for copy-paste only.
    print("\n=== Access Token Generated ===")
    print("\nYour new access token (copy it now — it will not be shown again):")
    print(f"\n  ZERODHA_ACCESS_TOKEN={access_token}\n")
    print("Add this to your .env file:")
    print("  ZERODHA_ACCESS_TOKEN=<paste here>\n")
    print("IMPORTANT: Never commit your .env file to version control.\n")

    # Optionally write to .env.
    if args.write_env:
        env_path = Path(args.env_file)
        if not env_path.exists():
            print(
                f"[WARNING] --write-env specified but {env_path} does not exist.\n"
                "Create the file first (copy from .env.example).\n"
            )
            return 1
        try:
            update_env_file(env_path, access_token)
            print(f"[OK] Updated ZERODHA_ACCESS_TOKEN in {env_path}.")
            print("     (Token value was not logged.)")
        except Exception as exc:
            print(f"[ERROR] Could not update {env_path}: {exc}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
