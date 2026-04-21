"""Detect AMP pages or alternative markup variants."""

from __future__ import annotations

import logging
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def is_amp_url(url: str) -> bool:
    """Return True when the URL likely points to an AMP page."""

    parsed = urlparse(url)
    return parsed.path.endswith("/amp") or "/amp/" in parsed.path or "?amp" in parsed.query


def find_amp_alternate(html: str, base_url: str) -> str | None:
    """Inspect markup for AMP alternate links."""

    soup = BeautifulSoup(html, "lxml")
    link = soup.find("link", rel=lambda rel: rel and "amphtml" in rel)
    if link and link.get("href"):
        return urljoin(base_url, link["href"])
    return None


def _parse_amp_link_header(link_header: str, base_url: str) -> Optional[str]:
    """Extract the AMP target from an RFC 5988 ``Link`` header, if present."""
    # Example: '<https://example.com/page?amp>; rel="amphtml"'
    for part in link_header.split(","):
        part = part.strip()
        if 'rel="amphtml"' not in part and "rel=amphtml" not in part:
            continue
        if "<" in part and ">" in part:
            href = part[part.index("<") + 1 : part.index(">")].strip()
            if href:
                return urljoin(base_url, href)
    return None


def probe_for_amp(
    url: str,
    *,
    timeout: float = 8.0,
    headers: Optional[dict[str, str]] = None,
    logger: Optional[logging.Logger] = None,
) -> Tuple[str, bool]:
    """Return an AMP variant for ``url`` when one is available.

    Tries a HEAD request first and parses the ``Link: rel="amphtml"`` header.
    Only falls back to a full GET (with HTML parsing) when HEAD doesn't
    surface an AMP advertisement. Any network failure is swallowed.
    """

    if is_amp_url(url):
        return url, True

    request_headers = {**_DEFAULT_HEADERS, **(headers or {})}
    try:
        with httpx.Client(headers=request_headers, follow_redirects=True, timeout=timeout) as client:
            try:
                head = client.head(url)
                link_header = head.headers.get("Link") or head.headers.get("link")
                if link_header:
                    amp_candidate = _parse_amp_link_header(link_header, str(head.url))
                    if amp_candidate:
                        if logger:
                            logger.debug(
                                "AMP variant discovered via HEAD Link: %s -> %s",
                                url,
                                amp_candidate,
                            )
                        return amp_candidate, True
            except httpx.HTTPError:
                # HEAD can fail on sites that reject the method; fall through to GET.
                pass

            response = client.get(url)
            response.raise_for_status()
            amp_candidate = find_amp_alternate(response.text, str(response.url))
    except httpx.HTTPError as exc:  # pragma: no cover - network variability
        if logger:
            logger.debug("AMP probe failed for %s: %s", url, exc)
        return url, False

    if amp_candidate:
        if logger:
            logger.debug("AMP variant discovered for %s -> %s", url, amp_candidate)
        return amp_candidate, True

    if logger:
        logger.debug("No AMP variant advertised for %s", url)
    return url, False
