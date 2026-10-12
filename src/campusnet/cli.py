from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import sys
from urllib.parse import urlparse

from .config import AppConfig, write_config, load_config, validate_portal_base_url
from .credentials import CredentialError, delete_credentials, save_credentials
from .monitor import run_app


def setup() -> int:
    print("CampusNet setup — credentials are saved in your OS credential store, not in config.toml.\n")
    print("Enter the login entry URL without its temporary query token.")
    print("For the portal in your screenshots, use: https://192.168.55.253:1003/fgtauth")
    print("After login, the portal redirects to /keepalive?<temporary-token>; CampusNet checks that page automatically.")
    portal_url = input("College portal base URL: ").strip()
    try:
        portal_url = validate_portal_base_url(portal_url)
    except ValueError as exc:
        print(f"Invalid portal URL: {exc}", file=sys.stderr)
        return 2
    parsed = urlparse(portal_url)
    if parsed.scheme != "https":
        print("Warning: the portal URL is not HTTPS. Do not enter college credentials unless this is confirmed as the official portal.")
    print("Note: your screenshot shows a browser trust warning. CampusNet verifies certificates by default.")
    print("Only consider ignore_portal_tls_errors=true after verifying the portal with your college IT team.")
    username = input("College username: ").strip()
    password = getpass.getpass("College password (input hidden): ")
    if not portal_url or not username or not password:
        print("Portal URL, username, and password are required.", file=sys.stderr)
        return 2

    try:
        save_credentials(username, password)
        config = AppConfig(portal_url=portal_url)
        path = write_config(config)
    except (CredentialError, ValueError, OSError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 2

    print(f"\nConfiguration saved to: {path}")
    print("Next: run `campusnet run --show-browser` to verify the portal selectors and keepalive page.")
    print("Do not share config.toml, browser traces, or logs if they contain portal-specific information.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="campusnet",
        description="Maintain a Fortinet captive-portal session and recover through the normal login page.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("setup", help="Configure the portal and securely save your credentials.")
    run_parser = subparsers.add_parser("run", help="Start background monitoring and portal recovery.")
    run_parser.add_argument(
        "--show-browser",
        action="store_true",
        help="Show the browser for troubleshooting or manual verification steps.",
    )
    subparsers.add_parser("reset-credentials", help="Delete CampusNet credentials from the OS credential store.")

    args = parser.parse_args()
    if args.command == "setup":
        raise SystemExit(setup())
    if args.command == "reset-credentials":
        try:
            delete_credentials()
        except CredentialError as exc:
            print(f"Could not fully remove credentials: {exc}", file=sys.stderr)
            raise SystemExit(2)
        print("CampusNet credentials removed from the OS credential store.")
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        config = load_config()
        asyncio.run(run_app(config, show_browser=args.show_browser))
    except KeyboardInterrupt:
        print("\nCampusNet stopped.")
    except (FileNotFoundError, ValueError, CredentialError) as exc:
        print(f"CampusNet could not start: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except Exception as exc:
        logging.exception("Unexpected error: %s", exc)
        raise SystemExit(1)
