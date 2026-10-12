from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from platformdirs import user_config_path

APP_NAME = "CampusNet"
CONFIG_DIR = user_config_path(APP_NAME, appauthor=False)
CONFIG_PATH = CONFIG_DIR / "config.toml"


@dataclass(frozen=True)
class AppConfig:
    # Base URL only. The temporary FortiGate query token is discovered at runtime.
    portal_url: str
    # The authenticated FortiGate page shown after login is /keepalive?<temporary-token>.
    keepalive_path: str = "/keepalive"
    keepalive_success_text: str = "Authentication Keepalive"
    username_selector: str = "input[name='username'], input[type='text']"
    password_selector: str = "input[name='password'], input[type='password']"
    submit_selector: str = "button[type='submit'], input[type='submit']"
    # Plain HTTP is intentional: captive portals commonly intercept HTTP probes and redirect them.
    connectivity_url: str = "http://connectivitycheck.gstatic.com/generate_204"
    expected_status: int = 204
    check_interval_seconds: int = 30
    retry_delay_seconds: int = 20
    request_timeout_seconds: int = 8
    headless: bool = True
    # Keep certificate verification enabled by default. Only opt out after verifying the portal.
    ignore_portal_tls_errors: bool = False
    # Launch the desktop app automatically at user sign-in unless the user opts out.
    launch_at_startup: bool = True


def validate_http_url(value: object, field: str = "URL") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{field}' must be a non-empty URL.")
    stripped = value.strip()
    parsed = urlparse(stripped)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"'{field}' must start with http:// or https:// and include a host.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"'{field}' must not embed a username or password in the URL.")
    return stripped


def validate_portal_base_url(value: object) -> str:
    portal_url = validate_http_url(value, "portal_url")
    parsed = urlparse(portal_url)
    if parsed.query or parsed.fragment:
        raise ValueError(
            "'portal_url' must be the portal base URL without a query string or fragment. "
            "FortiGate's temporary authentication token is discovered at runtime and must not be saved."
        )
    return portal_url


def _positive_int(data: dict, key: str, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"'{key}' must be a positive integer.")
    return value


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(
            f"CampusNet is not configured. Run `campusnet setup` first.\n"
            f"Expected config file: {config_path}"
        )

    with config_path.open("rb") as f:
        data = tomllib.load(f)

    portal_url = validate_portal_base_url(data.get("portal_url"))
    defaults = AppConfig.__dataclass_fields__
    connectivity_url = validate_http_url(
        data.get("connectivity_url", defaults["connectivity_url"].default),
        "connectivity_url",
    )
    expected_status = _positive_int(data, "expected_status", defaults["expected_status"].default)
    check_interval = _positive_int(
        data, "check_interval_seconds", defaults["check_interval_seconds"].default
    )
    retry_delay = _positive_int(data, "retry_delay_seconds", defaults["retry_delay_seconds"].default)
    timeout = _positive_int(data, "request_timeout_seconds", defaults["request_timeout_seconds"].default)

    string_fields = (
        "keepalive_path",
        "keepalive_success_text",
        "username_selector",
        "password_selector",
        "submit_selector",
    )
    strings: dict[str, str] = {}
    for key in string_fields:
        value = data.get(key, defaults[key].default)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"'{key}' must be a non-empty string.")
        strings[key] = value.strip()

    headless = data.get("headless", True)
    if not isinstance(headless, bool):
        raise ValueError("'headless' must be true or false.")
    ignore_tls_errors = data.get("ignore_portal_tls_errors", False)
    if not isinstance(ignore_tls_errors, bool):
        raise ValueError("'ignore_portal_tls_errors' must be true or false.")
    launch_at_startup = data.get("launch_at_startup", True)
    if not isinstance(launch_at_startup, bool):
        raise ValueError("'launch_at_startup' must be true or false.")

    return AppConfig(
        portal_url=portal_url,
        connectivity_url=connectivity_url,
        expected_status=expected_status,
        check_interval_seconds=check_interval,
        retry_delay_seconds=retry_delay,
        request_timeout_seconds=timeout,
        headless=headless,
        ignore_portal_tls_errors=ignore_tls_errors,
        launch_at_startup=launch_at_startup,
        **strings,
    )


def write_config(config: AppConfig, path: Path | None = None) -> Path:
    config_path = path or CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"portal_url = {json.dumps(config.portal_url)}",
        f"keepalive_path = {json.dumps(config.keepalive_path)}",
        f"keepalive_success_text = {json.dumps(config.keepalive_success_text)}",
        f"username_selector = {json.dumps(config.username_selector)}",
        f"password_selector = {json.dumps(config.password_selector)}",
        f"submit_selector = {json.dumps(config.submit_selector)}",
        f"connectivity_url = {json.dumps(config.connectivity_url)}",
        f"expected_status = {config.expected_status}",
        f"check_interval_seconds = {config.check_interval_seconds}",
        f"retry_delay_seconds = {config.retry_delay_seconds}",
        f"request_timeout_seconds = {config.request_timeout_seconds}",
        f"headless = {'true' if config.headless else 'false'}",
        f"ignore_portal_tls_errors = {'true' if config.ignore_portal_tls_errors else 'false'}",
        f"launch_at_startup = {'true' if config.launch_at_startup else 'false'}",
        "",
    ]
    config_path.write_text("\n".join(lines), encoding="utf-8")
    try:
        config_path.chmod(0o600)
    except OSError:
        # Windows uses ACLs rather than POSIX file mode bits; do not fail setup.
        pass
    return config_path
