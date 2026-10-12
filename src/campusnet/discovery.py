from __future__ import annotations

import html
import re
from urllib.parse import urljoin, urlparse


_ABSOLUTE_URL_RE = re.compile(r"https?://[^\s\"'<>`]+", re.IGNORECASE)
_RELATIVE_AUTH_RE = re.compile(r"(?<![A-Za-z0-9])(/fgtauth(?:\?[^\s\"'<>`)]+)?)", re.IGNORECASE)


def _validated_candidate(base_url: str, candidate: str) -> str | None:
    """Accept a fresh token URL only on the configured FortiGate origin."""
    base = urlparse(base_url)
    parsed = urlparse(candidate)
    try:
        same_origin = (
            parsed.scheme.lower() == base.scheme.lower()
            and (parsed.hostname or "").lower() == (base.hostname or "").lower()
            and parsed.port == base.port
        )
    except ValueError:
        return None

    path_matches = (
        parsed.path.rstrip("/").lower() == base.path.rstrip("/").lower()
        or parsed.path.lower().endswith("/fgtauth")
    )
    # Your observed FortiGate flow puts its session-specific magic value in the query.
    # Never guess a token or submit credentials to a static URL without that value.
    if parsed.scheme.lower() != "https" or not same_origin or not path_matches or not parsed.query:
        return None
    return candidate


def resolve_portal_redirect(
    base_url: str,
    response_url: str,
    location: str | None,
    body: str | None = None,
) -> str | None:
    """Find a fresh FortiGate login URL in a redirect header or an intercepted HTML body.

    Some captive portals answer an HTTP connectivity probe with HTML (200 OK) instead of
    an HTTP Location redirect. This scans only for candidate URLs and validates every
    candidate against the configured FortiGate origin and /fgtauth path. Query tokens are
    returned only in memory; callers must never log or persist the returned URL.
    """
    if location:
        candidate = urljoin(response_url, location)
        accepted = _validated_candidate(base_url, candidate)
        if accepted:
            return accepted

    if not body:
        return None

    decoded = html.unescape(body[:256_000])
    base = urlparse(base_url)
    origin = f"{base.scheme}://{base.netloc}"
    candidates: list[str] = []

    # First inspect absolute URLs, including URLs embedded in JavaScript redirects.
    for match in _ABSOLUTE_URL_RE.findall(decoded):
        candidates.append(match.rstrip(".,;)}]"))

    # Then inspect root-relative FortiGate links such as /fgtauth?magic.
    for match in _RELATIVE_AUTH_RE.findall(decoded):
        candidates.append(urljoin(origin + "/", match))

    for candidate in candidates:
        accepted = _validated_candidate(base_url, candidate)
        if accepted:
            return accepted
    return None
