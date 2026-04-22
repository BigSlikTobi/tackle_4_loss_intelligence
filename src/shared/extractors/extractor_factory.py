"""Factory for selecting extraction strategies."""

from __future__ import annotations

import logging
from typing import Protocol
from urllib.parse import urlparse

from src.shared.contracts.extracted_content import ExtractedContent
from src.shared.utils.amp_detector import is_amp_url
from .light_extractor import LightExtractor
from .playwright_extractor import PlaywrightExtractor


class Extractor(Protocol):
    """Typing protocol for extractor implementations."""

    def extract(self, url: str, *, timeout: float | None = None, options: dict | None = None) -> ExtractedContent:
        """Extract article content for the provided URL."""


HEAVY_HOSTS = {
    "www.espn.com",
    "www.nfl.com",
    "sports.yahoo.com",
    "www.cbssports.com",
    "www.nbcsportsphiladelphia.com",
    "www.nbcsportschicago.com",
    "www.nbcsportsbayarea.com",
    "www.nbcsportsboston.com",
    "www.nbcsportswashington.com",
}

LIGHT_HOSTS = {
    "apnews.com",
    "www.si.com",
    "bleacherreport.com",
}

# Backwards-compatible private aliases
_HEAVY_HOSTS = HEAVY_HOSTS
_LIGHT_HOSTS = LIGHT_HOSTS


def is_heavy_url(url: str) -> bool:
    """Return True if ``url`` targets a host that requires Playwright."""
    try:
        hostname = urlparse(url).hostname or ""
        return hostname in HEAVY_HOSTS
    except Exception:
        return False


def get_extractor(
    url: str,
    *,
    force_playwright: bool = False,
    prefer_lightweight: bool = False,
    logger: logging.Logger | None = None,
) -> Extractor:
    """Return the appropriate extractor instance for the given URL and hints."""

    hostname = urlparse(url).hostname or ""
    if force_playwright:
        return PlaywrightExtractor(logger=logger)
    if prefer_lightweight:
        return LightExtractor(logger=logger)
    if hostname in _HEAVY_HOSTS:
        return PlaywrightExtractor(logger=logger)
    if hostname in _LIGHT_HOSTS:
        return LightExtractor(logger=logger)
    if is_amp_url(url):
        return LightExtractor(logger=logger)
    return LightExtractor(logger=logger)
