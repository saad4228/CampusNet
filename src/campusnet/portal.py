from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError, Page, TimeoutError as PlaywrightTimeoutError

from .config import AppConfig

LOG = logging.getLogger("campusnet.portal")


class PortalError(RuntimeError):
    """Base error for portal interaction failures."""


class AuthenticationRequired(PortalError):
    """The portal needs a login flow that could not be completed automatically."""


async def _visible_locator(page: Page, selector: str):
    locator = page.locator(selector).first
    try:
        if await locator.count() and await locator.is_visible():
            return locator
    except PlaywrightTimeoutError:
        pass
    return None


async def _body_text(page: Page) -> str:
    try:
        return (await page.locator("body").inner_text(timeout=3000))[:6000]
    except Exception:
        return ""


async def ensure_keepalive_page(
    page: Page,
    config: AppConfig,
    username: str,
    password: str,
    start_url: str | None = None,
) -> None:
    """Open the portal, submit a standard login form if present, then keep the resulting page alive.

    ``start_url`` may include a short-lived FortiGate query token discovered from a captive-portal
    redirect. It is used only in memory and must never be logged or persisted. The page's own JavaScript
    timer remains active while this browser page is kept open. No private firewall API is called.
    """
    LOG.info("Opening the configured authentication portal.")
    try:
        await page.goto(
            start_url or config.portal_url,
            wait_until="domcontentloaded",
            timeout=max(15_000, config.request_timeout_seconds * 1000),
        )
    except PlaywrightTimeoutError:
        LOG.warning("Portal navigation timed out; checking whether the page loaded anyway.")
    except PlaywrightError as exc:
        raise AuthenticationRequired(
            "Could not open the portal. Check that the network is connected and the portal certificate is trusted. "
            "CampusNet does not bypass TLS certificate checks by default."
        ) from exc

    await page.wait_for_timeout(1200)
    username_field = await _visible_locator(page, config.username_selector)
    password_field = await _visible_locator(page, config.password_selector)

    if username_field is not None and password_field is not None:
        LOG.info("Login form detected; submitting credentials through the portal form.")
        try:
            await username_field.fill(username)
            await password_field.fill(password)
            submit = await _visible_locator(page, config.submit_selector)
            if submit is not None:
                await submit.click(timeout=8000)
            else:
                await password_field.press("Enter")
            await page.wait_for_timeout(2200)
        except Exception as exc:
            raise AuthenticationRequired(
                "Could not submit the portal login form. Check the CSS selectors in config.toml."
            ) from exc

    # Check for rejected credentials before reporting success.
    body = await _body_text(page)
    lowered = body.lower()
    if any(term in lowered for term in ("invalid credentials", "incorrect password", "authentication failed")):
        raise AuthenticationRequired("The portal rejected the saved credentials. Run `campusnet setup` to update them.")

    # The provided screenshots show successful login redirecting from /fgtauth to
    # /keepalive?<temporary-token>. Validate the path and page text, but never log the
    # full URL because its query string may contain a session-specific value.
    for _ in range(8):
        body = await _body_text(page)
        current_path = urlparse(page.url).path.rstrip("/") or "/"
        expected_path = config.keepalive_path.rstrip("/") or "/"
        if (
            current_path.casefold() == expected_path.casefold()
            and config.keepalive_success_text.casefold() in body.casefold()
        ):
            LOG.info("Authenticated keepalive page detected at %s; leaving it open in the background.", current_path)
            return
        if await _visible_locator(page, config.password_selector) is not None:
            break
        await asyncio.sleep(0.5)

    body = await _body_text(page)
    if any(term in body.lower() for term in ("captcha", "verification code", "two-factor", "multi-factor")):
        raise AuthenticationRequired(
            "The portal appears to require CAPTCHA, a verification code, or another manual step. "
            "Run `campusnet run --show-browser` and complete it manually."
        )
    raise AuthenticationRequired(
        "Could not verify the keepalive page. Confirm portal_url, keepalive_path, and keepalive_success_text, "
        "then try `campusnet run --show-browser` to inspect the portal."
    )
