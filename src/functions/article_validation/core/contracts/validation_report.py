"""Response contract definitions for the article validation module."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

_ALLOWED_SEVERITIES = {"critical", "warning", "info"}
_ALLOWED_CATEGORIES = {"factual", "contextual", "quality", "general"}
_ALLOWED_STATUS = {"success", "partial", "error"}
_ALLOWED_DECISIONS = {"release", "reject", "review_required"}


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    """Clamp *value* into the inclusive range [minimum, maximum]."""

    return max(minimum, min(maximum, value))


def _default_timestamp() -> str:
    """Return an ISO 8601 timestamp in UTC."""

    return datetime.now(timezone.utc).isoformat()


@dataclass
class ValidationIssue:
    """Represents an individual validation issue discovered during processing."""

    severity: str
    category: str
    message: str
    location: Optional[str] = None
    suggestion: Optional[str] = None
    source_url: Optional[str] = None

    def __post_init__(self) -> None:
        self.severity = self._normalise_severity(self.severity)
        self.category = self._normalise_category(self.category)
        self.message = self._normalise_message(self.message)
        if self.location is not None:
            self.location = self.location.strip() or None
        if self.suggestion is not None:
            self.suggestion = self.suggestion.strip() or None
        if self.source_url is not None:
            self.source_url = self.source_url.strip() or None

    @staticmethod
    def _normalise_severity(value: str) -> str:
        severity = (value or "").strip().lower()
        if severity not in _ALLOWED_SEVERITIES:
            raise ValueError(f"Unsupported issue severity: {value!r}")
        return severity

    @staticmethod
    def _normalise_category(value: str) -> str:
        category = (value or "").strip().lower()
        if category not in _ALLOWED_CATEGORIES:
            raise ValueError(f"Unsupported issue category: {value!r}")
        return category

    @staticmethod
    def _normalise_message(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Issue message must be a non-empty string")
        return value.strip()

    def to_dict(self) -> Dict[str, Optional[str]]:
        """Serialise the issue to a plain dictionary."""

        return {
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "location": self.location,
            "suggestion": self.suggestion,
            "source_url": self.source_url,
        }


@dataclass
class ValidationDimension:
    """Aggregated results for a single validation dimension."""

    enabled: bool
    score: float = 0.0
    confidence: float = 0.0
    passed: bool = False
    issues: List[ValidationIssue] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.score = _clamp(float(self.score))
        self.confidence = _clamp(float(self.confidence))
        self.passed = bool(self.passed) if self.enabled else False
        normalised: list[ValidationIssue] = []
        for issue in self.issues:
            if isinstance(issue, ValidationIssue):
                normalised.append(issue)
            elif isinstance(issue, dict):
                normalised.append(ValidationIssue(**issue))
            else:
                raise ValueError("Issues must be ValidationIssue instances or dictionaries")
        self.issues = normalised
        if isinstance(self.details, dict):
            pass
        elif isinstance(self.details, Mapping):
            self.details = dict(self.details)
        elif self.details is None:
            self.details = {}
        else:
            raise ValueError("`details` must be a mapping of supplementary data")

    def add_issue(self, issue: ValidationIssue) -> None:
        """Append an issue to the dimension, ensuring the list remains mutable."""

        self.issues.append(issue)

    def extend_issues(self, issues: Iterable[ValidationIssue]) -> None:
        """Extend the issue list with an iterable of issues."""

        self.issues.extend(issues)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the dimension to a plain dictionary."""

        return {
            "enabled": self.enabled,
            "score": self.score,
            "confidence": self.confidence,
            "passed": self.passed,
            "issues": [issue.to_dict() for issue in self.issues],
            "details": self.details,
        }


@dataclass
class ValidationReport:
    """Complete validation report returned to callers."""

    status: str
    decision: str
    is_releasable: bool
    factual: ValidationDimension
    contextual: ValidationDimension
    quality: ValidationDimension
    rejection_reasons: List[str] = field(default_factory=list)
    review_reasons: List[str] = field(default_factory=list)
    article_type: str = "unknown"
    validation_timestamp: str = field(default_factory=_default_timestamp)
    processing_time_ms: int = 0
    error: Optional[str] = None

    def __post_init__(self) -> None:
        self.factual = self._ensure_dimension(self.factual, "factual")
        self.contextual = self._ensure_dimension(self.contextual, "contextual")
        self.quality = self._ensure_dimension(self.quality, "quality")
        self.status = self._normalise_status(self.status)
        self.decision = self._normalise_decision(self.decision)
        self.is_releasable = bool(self.is_releasable)
        self.article_type = (self.article_type or "unknown").strip().lower() or "unknown"
        self.processing_time_ms = self._validate_processing_time(self.processing_time_ms)
        self.rejection_reasons = self._normalise_reason_list(self.rejection_reasons)
        self.review_reasons = self._normalise_reason_list(self.review_reasons)
        if self.error is not None:
            self.error = self.error.strip() or None

    @staticmethod
    def _ensure_dimension(value: Any, name: str) -> ValidationDimension:
        if isinstance(value, ValidationDimension):
            return value
        if isinstance(value, dict):
            return ValidationDimension(**value)
        raise ValueError(f"{name} must be a ValidationDimension or mapping")

    @staticmethod
    def _normalise_status(value: str) -> str:
        status = (value or "").strip().lower()
        if status not in _ALLOWED_STATUS:
            raise ValueError(f"Unsupported report status: {value!r}")
        return status

    @staticmethod
    def _normalise_decision(value: str) -> str:
        decision = (value or "").strip().lower()
        if decision not in _ALLOWED_DECISIONS:
            raise ValueError(f"Unsupported decision value: {value!r}")
        return decision

    @staticmethod
    def _normalise_reason_list(values: Iterable[str]) -> List[str]:
        cleaned: List[str] = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError("Reasons must be strings")
            text = value.strip()
            if text:
                cleaned.append(text)
        return cleaned

    @staticmethod
    def _validate_processing_time(value: Any) -> int:
        try:
            numeric = int(value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise ValueError("Processing time must be an integer") from exc
        if numeric < 0:
            raise ValueError("Processing time must be non-negative")
        return numeric

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the report into a JSON-compatible dictionary."""

        return {
            "status": self.status,
            "decision": self.decision,
            "is_releasable": self.is_releasable,
            "factual": self.factual.to_dict(),
            "contextual": self.contextual.to_dict(),
            "quality": self.quality.to_dict(),
            "rejection_reasons": list(self.rejection_reasons),
            "review_reasons": list(self.review_reasons),
            "article_type": self.article_type,
            "validation_timestamp": self.validation_timestamp,
            "processing_time_ms": self.processing_time_ms,
            "error": self.error,
        }

    def summary(self) -> Dict[str, Any]:
        """Return a lightweight summary useful for logging."""

        return {
            "status": self.status,
            "decision": self.decision,
            "is_releasable": self.is_releasable,
            "scores": {
                "factual": self.factual.score,
                "contextual": self.contextual.score,
                "quality": self.quality.score,
            },
            "issues": {
                "factual": len(self.factual.issues),
                "contextual": len(self.contextual.issues),
                "quality": len(self.quality.issues),
            },
        }
