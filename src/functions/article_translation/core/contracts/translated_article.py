"""Placeholder contract definitions for translated articles."""

from dataclasses import dataclass
from typing import List, Optional


@dataclass(slots=True)
class TranslationRequest:
    """Input structure for translation requests."""

    language: str
    headline: str
    sub_header: str
    introduction_paragraph: str
    content: List[str]


@dataclass(slots=True)
class TranslatedArticle:
    """Output structure for translated team articles."""

    language: str
    headline: str
    sub_header: str
    introduction_paragraph: str
    content: List[str]
    error: Optional[str] = None
