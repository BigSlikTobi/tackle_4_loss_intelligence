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
)


def _filter_paragraphs(paragraphs: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    for paragraph in paragraphs:
        if not paragraph:
            continue
        trimmed = paragraph.strip()
        if len(trimmed) < 40:
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
