"""Contracts for the article summarization service."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, ValidationError, field_validator


class SummarizationOptions(BaseModel):
    """Tunable parameters controlling Gemini summarization."""

    model: str = Field(default="gemma-3n-e4b-it", description="Gemini model identifier")
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    max_output_tokens: int = Field(default=512, gt=0, le=2048)
    remove_patterns: list[str] = Field(
        default_factory=lambda: [
            "subscribe", "newsletter", "advertisement", "promo code", "follow us",
        ]
    )


class SummarizationRequest(BaseModel):
    """Validated input payload for the summarization service."""

    article_id: Optional[str] = Field(default=None, description="Identifier for traceability")
    team_name: Optional[str] = Field(default=None, description="Team context for prompt personalization")
    content: str = Field(..., min_length=40, description="Full article text to summarize")

    @field_validator("content")
    @classmethod
    def _normalize_content(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped.split()) < 25:
            msg = "Article content must contain at least 25 words for meaningful summarization"
            raise ValueError(msg)
        return stripped


class ArticleSummary(BaseModel):
    """Structured summary produced by the service."""

    content: str = Field(..., description="Cleaned summary text")
    source_article_id: Optional[str] = Field(default=None)
    word_count: int = Field(default=0)
    error: Optional[str] = Field(default=None)

    @field_validator("content")
    @classmethod
    def _trim_content(cls, value: str) -> str:
        return " ".join(value.strip().split())

    def validate_content(self) -> "ArticleSummary":
        """Ensure the summary carries meaningful information."""

        if self.error:
            return self
        if not self.content or len(self.content.split()) < 10:
            self.error = "Summary content is too short"
        self.word_count = len(self.content.split())
        return self


def parse_options(raw: dict | SummarizationOptions | None) -> SummarizationOptions:
    """Create a validated options object from raw input."""

    if raw is None:
        return SummarizationOptions()
    if isinstance(raw, SummarizationOptions):
        return raw
    try:
        return SummarizationOptions(**raw)
    except ValidationError as exc:  # pragma: no cover - defensive
        msg = ", ".join(error["msg"] for error in exc.errors())
        raise ValueError(f"Invalid summarization options: {msg}") from exc
