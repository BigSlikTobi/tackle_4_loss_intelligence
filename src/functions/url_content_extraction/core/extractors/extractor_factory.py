"""Factory for selecting extraction strategies."""

from __future__ import annotations

import logging
from typing import Protocol
from urllib.parse import urlparse

from ..contracts.extracted_content import ExtractedContent
from ..utils.amp_detector import is_amp_url
from .light_extractor import LightExtractor
from .playwright_extractor import PlaywrightExtractor


class Extractor(Protocol):
    """Typing protocol for extractor implementations."""

    def extract(self, url: str, *, timeout: float | None = None, options: dict | None = None) -> ExtractedContent:
        """Extract article content for the provided URL."""


_HEAVY_HOSTS = {
    "www.espn.com",
    "www.nfl.com",
    "sports.yahoo.com",
    "www.cbssports.com",
}

_LIGHT_HOSTS = {
    "apnews.com",
    "www.si.com",
    "bleacherreport.com",
}


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
