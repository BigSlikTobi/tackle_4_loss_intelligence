"""Placeholder contracts for summarization inputs and outputs."""

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class SummarizationRequest:
    """Input payload for the summarization service."""

    article_id: Optional[str]
    content: str


@dataclass(slots=True)
class ArticleSummary:
    """Structured summary produced by the service."""

    content: str
    source_article_id: Optional[str] = None
    error: Optional[str] = None
