"""Detect AMP pages or alternative markup variants."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


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
