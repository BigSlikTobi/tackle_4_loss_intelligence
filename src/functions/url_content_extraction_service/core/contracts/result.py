"""Terminal result payload returned to callers on /poll success."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ArticleOut:
    """One extracted article in the job result."""

    url: str
    title: str | None = None
    description: str | None = None
    author: str | None = None
    paragraphs: List[str] = field(default_factory=list)
    content: str = ""
    word_count: int = 0
    quotes: List[str] = field(default_factory=list)
    published_at: str | None = None
    metadata: Dict[str, Any] | None = None
    used_amp: bool = False
    error: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"url": self.url}
        if self.error is not None:
            out["error"] = self.error
            return out
        out["title"] = self.title
        out["description"] = self.description
        out["author"] = self.author
        out["paragraphs"] = self.paragraphs
        out["content"] = self.content
        out["word_count"] = self.word_count
        out["quotes"] = self.quotes
        if self.published_at is not None:
            out["published_at"] = self.published_at
        if self.metadata is not None:
            out["metadata"] = self.metadata
        if self.used_amp:
            out["used_amp"] = True
        return out


@dataclass
class JobResult:
    articles: List[ArticleOut]
    counts: Dict[str, int] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "articles": [a.to_dict() for a in self.articles],
            "counts": self.counts,
            "metrics": self.metrics,
        }
