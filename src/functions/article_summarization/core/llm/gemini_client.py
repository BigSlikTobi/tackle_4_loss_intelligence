"""Gemini client placeholder for article summarization."""

from typing import Any

from ..contracts.summary import ArticleSummary, SummarizationRequest


class GeminiSummarizationClient:
    """Handles calls to the Gemini API (implementation pending)."""

    def __init__(self, *, model: str = "gemma-3n") -> None:
        self.model = model

    def summarize(self, request: SummarizationRequest) -> ArticleSummary:
        """Return a placeholder summary result until Task 4 is completed."""
        return ArticleSummary(content="", source_article_id=request.article_id, error="Summarization not implemented")
