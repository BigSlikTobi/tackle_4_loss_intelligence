"""Request models and configuration for article knowledge extraction."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


MAX_ARTICLE_CHARS = 200_000


@dataclass
class LLMConfig:
    """OpenAI-compatible LLM configuration."""

    provider: str = "openai"
    model: str = "gpt-5.4-mini"
    api_key: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 60
    max_retries: int = 2


@dataclass
class SupabaseConfig:
    """Supabase credentials for the ephemeral job store."""

    url: str
    key: str
    jobs_table: str = "article_knowledge_extraction_jobs"


@dataclass
class ArticleInput:
    """Article content submitted for extraction."""

    text: str
    article_id: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None

    def validate(self) -> None:
        if not self.text or not self.text.strip():
            raise ValueError("article.text is required and must be non-empty")
        if len(self.text) > MAX_ARTICLE_CHARS:
            raise ValueError(
                f"article.text exceeds the {MAX_ARTICLE_CHARS}-character limit "
                f"(got {len(self.text)})"
            )


@dataclass
class ExtractionOptions:
    """Tunable options for a single extraction."""

    max_topics: int = 5
    max_entities: int = 15
    resolve_entities: bool = True
    confidence_threshold: float = 0.6

    def validate(self) -> None:
        if self.max_topics < 1:
            raise ValueError("options.max_topics must be >= 1")
        if self.max_entities < 1:
            raise ValueError("options.max_entities must be >= 1")
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("options.confidence_threshold must be in [0.0, 1.0]")


@dataclass
class SubmitRequest:
    """Incoming payload for the /submit endpoint."""

    article: ArticleInput
    options: ExtractionOptions = field(default_factory=ExtractionOptions)
    llm: Optional[LLMConfig] = None
    supabase: Optional[SupabaseConfig] = None

    def validate(self) -> None:
        self.article.validate()
        self.options.validate()
        if self.llm is None or not self.llm.api_key or not self.llm.model:
            raise ValueError("llm.api_key and llm.model are required")
        if self.supabase is None or not self.supabase.url or not self.supabase.key:
            raise ValueError("supabase.url and supabase.key are required")


@dataclass
class PollRequest:
    """Incoming payload for the /poll endpoint."""

    job_id: str
    supabase: Optional[SupabaseConfig] = None

    def validate(self) -> None:
        if not self.job_id:
            raise ValueError("job_id is required")
        if self.supabase is None or not self.supabase.url or not self.supabase.key:
            raise ValueError("supabase.url and supabase.key are required")


@dataclass
class WorkerRequest:
    """Internal payload fired by submit into the worker endpoint."""

    job_id: str
    supabase: Optional[SupabaseConfig] = None

    def validate(self) -> None:
        if not self.job_id:
            raise ValueError("job_id is required")
        if self.supabase is None or not self.supabase.url or not self.supabase.key:
            raise ValueError("supabase.url and supabase.key are required")
