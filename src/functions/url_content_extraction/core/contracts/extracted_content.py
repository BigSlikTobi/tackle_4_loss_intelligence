"""Placeholder dataclasses for extracted content structures."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(slots=True)
class ExtractedContent:
    """Structured representation of article content (populated in Task 2)."""

    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    paragraphs: List[str] = field(default_factory=list)
    author: Optional[str] = None
    quotes: List[str] = field(default_factory=list)
    error: Optional[str] = None
