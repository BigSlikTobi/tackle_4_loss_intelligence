"""Data contracts for content extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, HttpUrl, ValidationError, field_validator


class ExtractionOptions(BaseModel):
    """Configuration provided to extractors at runtime."""

    url: HttpUrl
    timeout_seconds: int = 45
    force_playwright: bool = False
    prefer_lightweight: bool = False
    max_paragraphs: int = 120
    min_paragraph_chars: int = 240

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("timeout_seconds")
    @classmethod
    def _validate_timeout(cls, value: int) -> int:
        if value <= 0:
            msg = "timeout_seconds must be positive"
            raise ValueError(msg)
        return min(value, 180)

    @field_validator("max_paragraphs")
    @classmethod
    def _validate_paragraphs(cls, value: int) -> int:
        if value <= 0:
            msg = "max_paragraphs must be positive"
            raise ValueError(msg)
        return value


@dataclass(slots=True)
class ExtractionMetadata:
    """Supplemental information collected during extraction."""

    fetched_at: datetime
    extractor: str
    duration_seconds: float
    page_language: Optional[str] = None
    raw_url: Optional[str] = None


@dataclass(slots=True)
class ExtractedContent:
    """Structured representation of article content."""

    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    paragraphs: List[str] = field(default_factory=list)
    author: Optional[str] = None
    quotes: List[str] = field(default_factory=list)
    published_at: Optional[datetime] = None
    metadata: Optional[ExtractionMetadata] = None
    error: Optional[str] = None

    def is_valid(self, *, min_paragraphs: int = 1) -> bool:
        """Return True when the extracted payload contains meaningful content."""

        if self.error:
            return False
        cleaned = [paragraph.strip() for paragraph in self.paragraphs if paragraph and paragraph.strip()]
        return len(cleaned) >= min_paragraphs

    def trim(self, *, max_paragraphs: int) -> None:
        """Limit the number of stored paragraphs in-place."""

        if max_paragraphs < 1:
            return
        self.paragraphs = self.paragraphs[:max_paragraphs]


def parse_options(raw_options: dict | ExtractionOptions) -> ExtractionOptions:
    """Create validated extraction options from raw input."""

    if isinstance(raw_options, ExtractionOptions):
        return raw_options
    try:
        return ExtractionOptions(**raw_options)
    except ValidationError as exc:  # pragma: no cover - defensive branch
        msg = ", ".join(error["msg"] for error in exc.errors())
        raise ValueError(f"Invalid extraction options: {msg}") from exc
