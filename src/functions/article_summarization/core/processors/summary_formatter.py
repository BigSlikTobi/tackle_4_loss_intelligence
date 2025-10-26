"""Placeholder formatter for cleaning LLM summaries."""

from ..contracts.summary import ArticleSummary


def format_summary(summary: ArticleSummary) -> ArticleSummary:
    """Normalize whitespace and remove noise (implementation pending)."""
    return summary
