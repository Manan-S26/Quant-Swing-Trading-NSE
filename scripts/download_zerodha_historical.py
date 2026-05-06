"""Download historical candle data from Zerodha for the configured universe.

Uses only read-only Zerodha APIs. Never places, modifies, or cancels orders.
Refuses to run if LIVE_TRADING_ENABLED=true.

Usage examples:

  # Dry run — shows what would be downloaded without calling Zerodha:
  python3 scripts/download_zerodha_historical.py \\
    --config configs/default.yaml \\
    --interval 5minute \\
    --from-date 2026-01-01 \\
    --to-date 2026-01-31 \\
    --dry-run

  # Download specific symbols:
  python3 scripts/download_zerodha_historical.py \\
    --config configs/default.yaml \\
    --interval 5minute \\
    --from-date 2026-01-01 \\
    --to-date 2026-01-31 \\
    --symbols RELIANCE INFY TCS

  # Download full universe:
  python3 scripts/download_zerodha_historical.py \\
    --config configs/default.yaml \\
    --interval 5minute \\
    --from-date 2026-01-01 \\
    --to-date 2026-01-31
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Ensure src/ is on the path when run directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trading_engine.common.config import load_settings  # noqa: E402
from trading_engine.data.universe import load_universe_config  # noqa: E402
from trading_engine.data.zerodha_downloader import (  # noqa: E402
    DownloadConfig,
    assert_live_trading_disabled,
    run_download,
)

_DEFAULT_INTERVAL = "5minute"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Zerodha historical candle data (read-only)."
    )
    parser.add_argument(
        "--config",
        default="configs/default.yaml",
        help="Path to YAML config file (default: configs/default.yaml)",
    )
    parser.add_argument(
        "--interval",
        default=None,
        help=f"Candle interval, e.g. 5minute, minute, day (default: {_DEFAULT_INTERVAL})",
    )
    parser.add_argument(
        "--from-date",
        dest="from_date",
        default=None,
        help="Start date YYYY-MM-DD (required unless --dry-run with no dates)",
    )
    parser.add_argument(
        "--to-date",
        dest="to_date",
        default=None,
        help="End date YYYY-MM-DD (required unless --dry-run with no dates)",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=[],
        help="Symbols to download (default: all symbols in universe config)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded without making API calls",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns exit code (0 = success, non-zero = error)."""
    args = _parse_args(argv)

    # Load settings — credentials come from environment / .env.
    settings = load_settings()

    # Hard safety gate — must happen before any broker instantiation.
    assert_live_trading_disabled(settings)

    # Check credentials (skip in dry-run mode — no API calls needed).
    if not args.dry_run:
        api_key = settings.zerodha_api_key.get_secret_value()
        api_secret = settings.zerodha_api_secret.get_secret_value()
        access_token = settings.zerodha_access_token.get_secret_value()
        missing = [
            name
            for name, val in [
                ("ZERODHA_API_KEY", api_key),
                ("ZERODHA_API_SECRET", api_secret),
                ("ZERODHA_ACCESS_TOKEN", access_token),
            ]
            if not val or val == "replace_me"
        ]
        if missing:
            print(
                f"\n[ERROR] Missing credentials: {missing}\n"
                "Set these in your .env file before downloading data.\n"
                "Run `python3 scripts/zerodha_login_helper.py` to generate an access token.\n"
                "Use --dry-run to preview the download without credentials.\n"
            )
            return 1

    # Load universe config.
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"[ERROR] Config file not found: {config_path}")
        return 1

    try:
        universe = load_universe_config(config_path)
    except Exception as exc:
        print(f"[ERROR] Failed to load universe config: {exc}")
        return 1

    # Resolve interval and dates.
    interval = args.interval or settings.historical_interval or _DEFAULT_INTERVAL

    from_date_str = args.from_date or settings.historical_from_date
    to_date_str = args.to_date or settings.historical_to_date

    if not args.dry_run and (not from_date_str or not to_date_str):
        print(
            "[ERROR] --from-date and --to-date are required for a real download.\n"
            "Use --dry-run to preview without dates, or pass both date flags.\n"
        )
        return 1

    # Parse dates (use placeholder values in dry-run when not provided).
    try:
        from_date = (
            datetime.strptime(from_date_str, "%Y-%m-%d") if from_date_str else datetime(2024, 1, 1)
        )
        to_date = (
            datetime.strptime(to_date_str, "%Y-%m-%d") if to_date_str else datetime(2024, 1, 5)
        )
    except ValueError as exc:
        print(f"[ERROR] Invalid date format: {exc}. Use YYYY-MM-DD.")
        return 1

    if to_date < from_date:
        print("[ERROR] --to-date must be on or after --from-date.")
        return 1

    data_dir = settings.data_dir

    config = DownloadConfig(
        universe=universe,
        interval=interval,
        from_date=from_date,
        to_date=to_date,
        data_dir=data_dir,
        symbols=args.symbols,
        dry_run=args.dry_run,
        save=True,
    )

    if args.dry_run:
        print("\n[DRY RUN] No Zerodha API calls will be made.")
        print(f"  Config:   {config_path}")
        print(f"  Interval: {interval}")
        print(f"  From:     {from_date.date()}")
        print(f"  To:       {to_date.date()}")
        print(f"  Symbols:  {config.target_symbols()}")
        print(f"  Data dir: {data_dir}")
        result = run_download(config, broker=None)
        result.print_summary()
        return 0

    # Real download — build the broker.
    try:
        from kiteconnect import KiteConnect  # type: ignore[import]
    except ImportError:
        print(
            "[ERROR] kiteconnect package is not installed.\n"
            "Install it with: pip install kiteconnect\n"
        )
        return 1

    kite = KiteConnect(api_key=settings.zerodha_api_key.get_secret_value())
    kite.set_access_token(settings.zerodha_access_token.get_secret_value())

    from trading_engine.broker.zerodha.client import ZerodhaBroker  # noqa: E402

    broker = ZerodhaBroker(kite_client=kite)
    broker.connect()

    print(f"\nDownloading {len(config.target_symbols())} symbol(s)…")
    result = run_download(config, broker=broker)
    result.print_summary()

    return 0 if not result.symbols_failed else 1


if __name__ == "__main__":
    sys.exit(main())
