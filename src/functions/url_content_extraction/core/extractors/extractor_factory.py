"""Factory for selecting extraction strategies."""

from typing import Protocol

from ..contracts.extracted_content import ExtractedContent
from .light_extractor import LightExtractor
from .playwright_extractor import PlaywrightExtractor


class Extractor(Protocol):
    """Typing protocol for extractor implementations."""

    def extract(self, url: str, *, timeout: float | None = None) -> ExtractedContent:  # pragma: no cover - structural stub
        """Extract article content for the provided URL."""


def get_extractor(*, force_playwright: bool = False) -> Extractor:
    """Return the appropriate extractor instance for the given options."""
    if force_playwright:
        return PlaywrightExtractor()
    return LightExtractor()
