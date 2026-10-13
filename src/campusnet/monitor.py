from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

import httpx
from playwright.async_api import async_playwright

from .config import AppConfig
from .credentials import load_credentials
from .discovery import resolve_portal_redirect
from .portal import AuthenticationRequired, ensure_keepalive_page

LOG = logging.getLogger("campusnet")

# Recovery backoff is capped so a long outage does not retry forever at speed.
MAX_RECOVERY_DELAY_SECONDS = 300


def should_attempt_recovery(
    fresh_portal_url: str | None,
    failures: int,
    now: float,
    next_recovery_at: float,
) -> bool:
    """Decide whether to run the portal flow after a failed connectivity probe.

    A fresh FortiGate redirect is positive proof that the portal has logged this
    device out, so recovery runs on the first failed probe. Without a redirect the
    failure may be an ordinary network blip, so a second consecutive failure is
    still required. The backoff window applies to both cases.
    """
    if now < next_recovery_at:
        return False
    return bool(fresh_portal_url) or failures >= 2


def next_check_delay(config: AppConfig, online: bool, recovered: bool) -> float:
    """Seconds to wait before the next connectivity probe."""
    if recovered:
        # Confirm the new session immediately so the UI reports the real state
        # instead of waiting out a full interval.
        return 0.0
    if online:
        return float(config.check_interval_seconds)
    return float(min(config.offline_check_interval_seconds, config.check_interval_seconds))


async def probe_connectivity(
    client: httpx.AsyncClient, config: AppConfig
) -> tuple[bool, str | None]:
    """Probe without following redirects so a FortiGate magic URL can be captured safely.

    Returns (online, fresh_portal_url). URLs with a temporary token are kept in memory
    and must not be logged or persisted.
    """
    try:
        response = await client.get(config.connectivity_url, follow_redirects=False)
        if response.status_code == config.expected_status:
            return True, None
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        body = response.text if content_type in {"text/html", "application/xhtml+xml", "text/plain", "application/javascript"} else None
        portal_url = resolve_portal_redirect(
            config.portal_url,
            str(response.request.url),
            response.headers.get("location"),
            body,
        )
        LOG.info(
            "Connectivity probe returned HTTP %s (content-type: %s); fresh portal URL %s.",
            response.status_code,
            content_type or "unknown",
            "detected" if portal_url else "not detected",
        )
        return False, portal_url
    except (httpx.HTTPError, TimeoutError):
        return False, None


async def discover_portal_in_browser(page, config: AppConfig) -> str | None:
    """Use Chromium itself as a fallback when the HTTP probe has no usable Location header.

    This can expose captive-portal redirects that differ between a browser and an HTTP client.
    The returned URL is validated and only kept in memory.
    """
    try:
        await page.goto(
            config.connectivity_url,
            wait_until="domcontentloaded",
            timeout=max(15_000, config.request_timeout_seconds * 1000),
        )
    except Exception:
        # Captive portals may interrupt the navigation; inspect the resulting page anyway.
        pass

    current_url = page.url
    direct = resolve_portal_redirect(config.portal_url, current_url, current_url)
    if direct:
        return direct

    try:
        body = (await page.locator("body").inner_text(timeout=3000))[:6000]
    except Exception:
        body = ""
    return resolve_portal_redirect(config.portal_url, current_url, None, body)


async def run_app(
    config: AppConfig,
    show_browser: bool = False,
    stop_event: asyncio.Event | None = None,
) -> None:
    username, password = load_credentials()
    headless = config.headless and not show_browser

    LOG.info("Starting CampusNet (headless browser: %s).", headless)
    LOG.info("Press Ctrl+C to stop. Credentials are read from the OS credential store.")
    LOG.info("Temporary captive-portal tokens are discovered at runtime and are not saved.")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        context = await browser.new_context(ignore_https_errors=config.ignore_portal_tls_errors)
        page = await context.new_page()
        page.set_default_timeout(8000)

        try:
            async with httpx.AsyncClient(
                timeout=config.request_timeout_seconds,
                follow_redirects=False,
                headers={"User-Agent": "CampusNet/0.4 (connectivity-check)"},
            ) as client:
                failures = 0
                recovery_delay = config.retry_delay_seconds
                next_recovery_at = 0.0
                loop = asyncio.get_running_loop()

                # Start authentication only from a fresh redirect. FortiGate's query token
                # may be required for the form submission and must not be guessed/reused.
                online, portal_url = await probe_connectivity(client, config)
                if not online and not portal_url:
                    LOG.info("Trying Chromium-based captive-portal redirect discovery.")
                    portal_url = await discover_portal_in_browser(page, config)
                    if portal_url:
                        LOG.info("A fresh portal redirect was discovered in the browser.")
                if portal_url:
                    try:
                        await ensure_keepalive_page(
                            page, config, username, password, start_url=portal_url
                        )
                        LOG.info("Portal flow completed; background monitoring has started.")
                    except AuthenticationRequired as exc:
                        LOG.error("Initial portal authentication needs attention: %s", exc)
                        LOG.info("CampusNet will keep monitoring and retry when a fresh portal redirect appears.")
                elif online:
                    LOG.warning(
                        "Internet is already available, so no fresh portal token was found. "
                        "CampusNet will monitor the connection and recover when a new portal redirect appears. "
                        "For proactive keepalive from the start, launch CampusNet before submitting the portal login."
                    )
                else:
                    LOG.warning(
                        "Connectivity failed, but no valid FortiGate redirect was detected. "
                        "CampusNet will keep monitoring; it will not submit credentials to a URL without a fresh token."
                    )

                while stop_event is None or not stop_event.is_set():
                    online, fresh_portal_url = await probe_connectivity(client, config)
                    now = loop.time()
                    recovered = False
                    if online:
                        if failures:
                            LOG.info("Internet access has recovered.")
                        failures = 0
                        recovery_delay = config.retry_delay_seconds
                        next_recovery_at = 0.0
                    else:
                        failures += 1
                        LOG.warning("Connectivity check failed (%s consecutive check(s)).", failures)
                        # A fresh redirect means the portal logged us out, so recover at
                        # once. Otherwise require a second failure, and back off either
                        # way to avoid rapid re-logins during outages.
                        if should_attempt_recovery(fresh_portal_url, failures, now, next_recovery_at):
                            if fresh_portal_url:
                                try:
                                    await ensure_keepalive_page(
                                        page,
                                        config,
                                        username,
                                        password,
                                        start_url=fresh_portal_url,
                                    )
                                    LOG.info("Portal authentication/keepalive was refreshed.")
                                    recovered = True
                                except AuthenticationRequired as exc:
                                    LOG.error("Automatic recovery needs attention: %s", exc)
                            else:
                                LOG.info("Trying Chromium-based discovery after the failed connectivity checks.")
                                browser_portal_url = await discover_portal_in_browser(page, config)
                                if browser_portal_url:
                                    try:
                                        await ensure_keepalive_page(
                                            page,
                                            config,
                                            username,
                                            password,
                                            start_url=browser_portal_url,
                                        )
                                        LOG.info("Portal authentication/keepalive was refreshed via browser discovery.")
                                        recovered = True
                                    except AuthenticationRequired as exc:
                                        LOG.error("Automatic recovery needs attention: %s", exc)
                                else:
                                    LOG.warning(
                                        "No fresh portal redirect was detected in the HTTP response or browser. "
                                        "This may be a network outage or a JavaScript-only captive portal; "
                                        "no credentials were submitted."
                                    )
                            next_recovery_at = loop.time() + recovery_delay
                            recovery_delay = min(recovery_delay * 2, MAX_RECOVERY_DELAY_SECONDS)
                            failures = 0
                    delay = next_check_delay(config, online, recovered)
                    if delay <= 0:
                        continue
                    if stop_event is None:
                        await asyncio.sleep(delay)
                    else:
                        try:
                            await asyncio.wait_for(stop_event.wait(), timeout=delay)
                        except TimeoutError:
                            pass
        finally:
            with suppress(Exception):
                await context.close()
            with suppress(Exception):
                await browser.close()
