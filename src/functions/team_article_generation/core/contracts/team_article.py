"""Placeholder contract definitions for generated team articles."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(slots=True)
class SummaryBundle:
    """Collection of summaries related to one team."""

    team_abbr: str
    summaries: List[str] = field(default_factory=list)


@dataclass(slots=True)
class GeneratedArticle:
    """Structured article representation produced by GPT-5."""

    headline: str
    sub_header: str
    introduction_paragraph: str
    content: List[str] = field(default_factory=list)
    error: Optional[str] = None
