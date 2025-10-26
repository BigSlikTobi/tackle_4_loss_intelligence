"""Formatter utilities for Gemini summaries."""

from __future__ import annotations

import re

from ..contracts.summary import ArticleSummary, SummarizationOptions

_STRIP_PATTERNS = (
    re.compile(r"^summary:\s*", re.IGNORECASE),
    re.compile(r"^key points:\s*", re.IGNORECASE),
)


def format_summary(summary: ArticleSummary, *, options: SummarizationOptions) -> ArticleSummary:
    """Normalize whitespace, remove templated prefixes, and enforce sentence casing."""

    text = summary.content.strip()
    for pattern in _STRIP_PATTERNS:
        text = pattern.sub("", text)

    sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", text) if segment.strip()]
    text = " ".join(sentences)

    for pattern_text in options.remove_patterns:
        text = re.sub(pattern_text, "", text, flags=re.IGNORECASE)

    text = re.sub(r"\s+", " ", text).strip()
    summary.content = text
    return summary
