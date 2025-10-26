"""Paragraph deduplication utilities."""

from __future__ import annotations

from collections import OrderedDict

from ..contracts.extracted_content import ExtractedContent


def deduplicate_paragraphs(content: ExtractedContent) -> ExtractedContent:
    """Remove duplicate paragraphs while preserving order."""

    seen: "OrderedDict[str, None]" = OrderedDict()
    for paragraph in content.paragraphs:
        if not paragraph:
            continue
        normalized = " ".join(paragraph.split())
        if normalized not in seen:
            seen[normalized] = None
    content.paragraphs = list(seen.keys())
    return content
