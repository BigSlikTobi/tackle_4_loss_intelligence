"""Contracts for article translation requests and responses."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, ValidationError, field_validator


class TranslationOptions(BaseModel):
    """Configuration passed to the translation client."""

    model: str = Field(default="gpt-5-mini")
    service_tier: str = Field(default="flex")
    request_timeout_seconds: int = Field(default=360, ge=180, le=1200)
    temperature: float | None = Field(default=None, description="Sampling temperature if supported")
    max_output_tokens: int | None = Field(default=None, description="Token limit if supported")
    tone_guidance: str = Field(
        default=(
            "Write in the style of professional German sports journalism. "
            "Keep sentences active and concise."
        )
    )
    structure_guidance: str = Field(
        default="Maintain the paragraph structure of the original article without merging sections."
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


class TranslationRequest(BaseModel):
    """Validated input payload for translation."""

    article_id: Optional[str] = Field(default=None)
    language: str = Field(..., min_length=2, description="Target language code")
    source_language: str = Field(default="en", min_length=2)
    headline: str = Field(..., min_length=3)
    sub_header: str = Field(..., min_length=3)
    introduction_paragraph: str = Field(..., min_length=10)
    content: list[str] = Field(default_factory=list)
    preserve_terms: list[str] = Field(default_factory=list)

    @field_validator("content")
    @classmethod
    def _validate_content(cls, paragraphs: list[str]) -> list[str]:
        cleaned = [paragraph.strip() for paragraph in paragraphs if paragraph and paragraph.strip()]
        if not cleaned:
            msg = "Translation request must include at least one content paragraph"
            raise ValueError(msg)
        return cleaned


class TranslatedArticle(BaseModel):
    """Structured translation payload."""

    language: str
    headline: str
    sub_header: str
    introduction_paragraph: str
    content: list[str]
    source_article_id: Optional[str] = Field(default=None)
    preserved_terms: list[str] = Field(default_factory=list)
    error: Optional[str] = Field(default=None)
    word_count: int = Field(default=0)

    @field_validator("content")
    @classmethod
    def _validate_content(cls, paragraphs: list[str]) -> list[str]:
        cleaned = [paragraph.strip() for paragraph in paragraphs if paragraph and paragraph.strip()]
        if not cleaned:
            msg = "Translated article must include at least one paragraph"
            raise ValueError(msg)
        return cleaned

    def compute_word_count(self) -> "TranslatedArticle":
        """Refresh cached word count for reporting."""

        self.word_count = sum(len(paragraph.split()) for paragraph in self.content)
        return self


def parse_translation_options(raw: dict | TranslationOptions | None) -> TranslationOptions:
    """Build validated translation options from raw input."""

    if raw is None:
        return TranslationOptions()
    if isinstance(raw, TranslationOptions):
        return raw
    try:
        return TranslationOptions(**raw)
    except ValidationError as exc:  # pragma: no cover - defensive
        msg = ", ".join(error["msg"] for error in exc.errors())
        raise ValueError(f"Invalid translation options: {msg}") from exc
