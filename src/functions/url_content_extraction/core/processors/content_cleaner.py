"""Content cleaning routines for extracted articles."""

from __future__ import annotations

import re
from typing import Iterable

from ..contracts.extracted_content import ExtractedContent


_AD_PATTERNS = (
    re.compile(r"subscribe now", re.IGNORECASE),
    re.compile(r"sign up for our newsletter", re.IGNORECASE),
    re.compile(r"advertisement", re.IGNORECASE),
    re.compile(r"cookie policy", re.IGNORECASE),
    re.compile(r"keyboard shortcuts?\s*(enabled|disabled)", re.IGNORECASE),
    re.compile(r"volume \d+%", re.IGNORECASE),
    re.compile(r"<iframe\s+src=", re.IGNORECASE),
    re.compile(r"jwplayer|jwplatform", re.IGNORECASE),
    re.compile(r"^\d+ seconds of \d+ seconds", re.IGNORECASE),
    re.compile(r"^(fullscreen|decrease|increase)\s+(caption|volume)", re.IGNORECASE),
    re.compile(r"^Link(https?://|copied)", re.IGNORECASE),
    re.compile(r"^Embed<", re.IGNORECASE),
    re.compile(r"frameborder=", re.IGNORECASE),
    re.compile(r"cdn\.jwplayer\.com", re.IGNORECASE),
    re.compile(r"^\d{1,2}:\d{2}[A-Z]", re.IGNORECASE),  # Timestamps like "00:47" followed by caps
)


def _filter_paragraphs(paragraphs: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    for paragraph in paragraphs:
        if not paragraph:
            continue
        trimmed = paragraph.strip()
        if len(trimmed) < 20:
            continue
        # Skip timestamps (e.g., "00:47", "14:21")
        if re.match(r'^\d{1,2}:\d{2}', trimmed):
            continue
        if any(pattern.search(trimmed) for pattern in _AD_PATTERNS):
            continue
        cleaned.append(trimmed)
    return cleaned


def clean_content(content: ExtractedContent) -> ExtractedContent:
    """Remove boilerplate, navigation text, and placeholder copy."""

    content.paragraphs = _filter_paragraphs(content.paragraphs)
    content.quotes = [quote.strip() for quote in content.quotes if quote and quote.strip()]
    return content
