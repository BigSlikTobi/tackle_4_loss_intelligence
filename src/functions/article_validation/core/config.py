"""Configuration models for the article validation module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

_ALLOWED_TIMEOUT_RANGE = (10, 300)
_VALIDATION_TIMEOUT_RANGE = (30, 120)


def _ensure_non_empty(value: Optional[str], field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be provided")
    return value.strip()


def _ensure_timeout(value: int, field_name: str, bounds: tuple[int, int]) -> int:
    minimum, maximum = bounds
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(
            f"{field_name} must be between {minimum} and {maximum} seconds"
        )
    return value


def _ensure_ratio(value: float, field_name: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if numeric < 0.0 or numeric > 1.0:
        raise ValueError(f"{field_name} must be within 0.0 and 1.0 inclusive")
    return numeric


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    raise ValueError("Boolean configuration values must be bools or boolean strings")


@dataclass
class LLMConfig:
    """Configuration for the Gemini client used during validation."""

    model: str = "gemini-2.5-flash-lite"
    api_key: Optional[str] = None
    enable_web_search: bool = True
    timeout_seconds: int = 60

    def validate(self) -> None:
        self.model = _ensure_non_empty(self.model, "model")
        self.api_key = _ensure_non_empty(self.api_key, "api_key")
        if not isinstance(self.enable_web_search, bool):
            self.enable_web_search = _coerce_bool(self.enable_web_search)
        self.timeout_seconds = _ensure_timeout(
            self.timeout_seconds,
            "timeout_seconds",
            _ALLOWED_TIMEOUT_RANGE,
        )


@dataclass
class ValidationConfig:
    """Behaviour controls for the validation workflow."""

    enable_factual: bool = True
    enable_contextual: bool = True
    enable_quality: bool = True
    factual_threshold: float = 0.7
    contextual_threshold: float = 0.7
    quality_threshold: float = 0.7
    confidence_threshold: float = 0.8
    timeout_seconds: int = 90

    def validate(self) -> None:
        for attr in ("enable_factual", "enable_contextual", "enable_quality"):
            value = getattr(self, attr)
            if not isinstance(value, bool):
                setattr(self, attr, _coerce_bool(value))
        self.factual_threshold = _ensure_ratio(self.factual_threshold, "factual_threshold")
        self.contextual_threshold = _ensure_ratio(
            self.contextual_threshold,
            "contextual_threshold",
        )
        self.quality_threshold = _ensure_ratio(self.quality_threshold, "quality_threshold")
        self.confidence_threshold = _ensure_ratio(
            self.confidence_threshold,
            "confidence_threshold",
        )
        self.timeout_seconds = _ensure_timeout(
            int(self.timeout_seconds),
            "timeout_seconds",
            _VALIDATION_TIMEOUT_RANGE,
        )


@dataclass
class SupabaseConfig:
    """Optional Supabase connection details for persistence."""

    url: str
    key: str
    table: str = "article_validations"
    schema: Optional[str] = None

    def validate(self) -> None:
        self.url = _ensure_non_empty(self.url, "url")
        self.key = _ensure_non_empty(self.key, "key")
        self.table = _ensure_non_empty(self.table, "table")
        if self.schema is not None and not self.schema.strip():
            self.schema = None