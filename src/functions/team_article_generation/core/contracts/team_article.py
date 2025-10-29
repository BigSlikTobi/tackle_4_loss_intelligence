"""Contracts for team article generation."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, ValidationError, field_validator


class GenerationOptions(BaseModel):
    """Configuration for GPT-5 article generation."""

    model: str = Field(default="gpt-5", description="OpenAI model identifier")
    temperature: float | None = Field(default=None, description="Sampling temperature if supported")
    max_output_tokens: int | None = Field(default=None, description="Maximum output tokens if supported")
    service_tier: str | None = Field(default=None, description="OpenAI service tier (e.g., 'flex'); omit if not supported")
    request_timeout_seconds: int = Field(default=600, ge=60, le=900)
    narrative_focus: str = Field(
        default=(
            "Focus on the primary storyline emerging from the provided summaries. "
            "Do not fabricate statistics, quotes, or predictions."
        )
    )

    @field_validator("temperature")
    @classmethod
    def _validate_temperature(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not (0.0 <= value <= 1.0):
            msg = "temperature must be between 0.0 and 1.0"
            raise ValueError(msg)
        return value

    @field_validator("max_output_tokens")
    @classmethod
    def _validate_max_tokens(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value <= 0 or value > 4000:
            msg = "max_output_tokens must be between 1 and 4000"
            raise ValueError(msg)
        return value


class SummaryBundle(BaseModel):
    """Collection of summaries related to one team."""

    team_abbr: str = Field(..., min_length=2, max_length=4)
    team_name: Optional[str] = Field(default=None)
    summaries: list[str] = Field(default_factory=list)

    @field_validator("summaries")
    @classmethod
    def _ensure_summaries(cls, value: list[str]) -> list[str]:
        cleaned = [summary.strip() for summary in value if summary and summary.strip()]
        if not cleaned:
            msg = "Summary bundle must include at least one non-empty summary"
            raise ValueError(msg)
        return cleaned


class GeneratedArticle(BaseModel):
    """Structured article representation produced by GPT-5."""

    headline: str
    sub_header: str
    introduction_paragraph: str
    content: list[str]
    central_theme: Optional[str] = None
    error: Optional[str] = None

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: list[str]) -> list[str]:
        cleaned = [paragraph.strip() for paragraph in value if paragraph and paragraph.strip()]
        if not cleaned:
            msg = "Generated article content cannot be empty"
            raise ValueError(msg)
        return cleaned

    def validate(self) -> "GeneratedArticle":
        """Ensure headline, sub-header, and intro are provided."""

        if self.error:
            return self
        missing = [
            field
            for field, value in (
                ("headline", self.headline.strip()),
                ("sub_header", self.sub_header.strip()),
                ("introduction_paragraph", self.introduction_paragraph.strip()),
            )
            if not value
        ]
        if missing:
            self.error = f"Missing required fields: {', '.join(missing)}"
        return self


def parse_generation_options(raw: dict | GenerationOptions | None) -> GenerationOptions:
    """Create validated generation options from raw input."""

    if raw is None:
        return GenerationOptions()
    if isinstance(raw, GenerationOptions):
        return raw
    try:
        return GenerationOptions(**raw)
    except ValidationError as exc:  # pragma: no cover - defensive
        msg = ", ".join(error["msg"] for error in exc.errors())
        raise ValueError(f"Invalid generation options: {msg}") from exc
