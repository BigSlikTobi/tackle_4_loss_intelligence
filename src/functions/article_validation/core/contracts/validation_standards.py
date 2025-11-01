"""Validation standards contract definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional

_ALLOWED_RULE_SEVERITY = {"critical", "warning", "info"}


def _ensure_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _normalise_severity(value: Optional[str]) -> str:
    if value is None:
        return "warning"
    severity = value.strip().lower()
    if severity not in _ALLOWED_RULE_SEVERITY:
        raise ValueError(f"Unsupported severity value: {value!r}")
    return severity


def _normalise_weight(value: Any) -> float:
    try:
        weight = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Rule weight must be numeric") from exc
    if weight <= 0:
        raise ValueError("Rule weight must be greater than zero")
    return weight


def _coerce_metadata(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("Metadata must be a mapping if provided")
    return dict(value)


@dataclass
class QualityRule:
    """Definition of a single quality validation rule."""

    identifier: str
    description: str
    weight: float = 1.0
    prompt: Optional[str] = None
    severity: str = "warning"
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.identifier = _ensure_non_empty_string(self.identifier, "identifier")
        self.description = _ensure_non_empty_string(self.description, "description")
        self.weight = _normalise_weight(self.weight)
        self.severity = _normalise_severity(self.severity)
        self.enabled = bool(self.enabled)
        self.metadata = _coerce_metadata(self.metadata)
        if self.prompt is not None:
            self.prompt = self.prompt.strip() or None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier,
            "description": self.description,
            "weight": self.weight,
            "prompt": self.prompt,
            "severity": self.severity,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }


@dataclass
class ContextualRequirement:
    """Definition of a contextual validation requirement."""

    identifier: str
    description: str
    enabled: bool = True
    severity: str = "warning"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.identifier = _ensure_non_empty_string(self.identifier, "identifier")
        self.description = _ensure_non_empty_string(self.description, "description")
        self.enabled = bool(self.enabled)
        self.severity = _normalise_severity(self.severity)
        self.metadata = _coerce_metadata(self.metadata)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier,
            "description": self.description,
            "enabled": self.enabled,
            "severity": self.severity,
            "metadata": self.metadata,
        }


@dataclass
class FactualVerificationRule:
    """Definition of a factual verification rule."""

    identifier: str
    description: str
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.identifier = _ensure_non_empty_string(self.identifier, "identifier")
        self.description = _ensure_non_empty_string(self.description, "description")
        self.enabled = bool(self.enabled)
        self.metadata = _coerce_metadata(self.metadata)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identifier": self.identifier,
            "description": self.description,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }


@dataclass
class ValidationStandards:
    """Container for all validation standards associated with an article type."""

    article_type: str
    version: str
    quality_rules: Dict[str, QualityRule] = field(default_factory=dict)
    contextual_requirements: Dict[str, ContextualRequirement] = field(default_factory=dict)
    factual_verification: Dict[str, FactualVerificationRule] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.article_type = _ensure_non_empty_string(self.article_type, "article_type").lower()
        self.version = _ensure_non_empty_string(self.version, "version")
        self.quality_rules = self._normalise_quality_rules(self.quality_rules)
        self.contextual_requirements = self._normalise_contextual_requirements(
            self.contextual_requirements
        )
        self.factual_verification = self._normalise_factual_rules(self.factual_verification)
        self.metadata = _coerce_metadata(self.metadata)

    @staticmethod
    def _normalise_quality_rules(rules: Mapping[str, Any] | Iterable[Any]) -> Dict[str, QualityRule]:
        normalised: Dict[str, QualityRule] = {}
        if isinstance(rules, Mapping):
            iterable = rules.items()
        else:
            iterable = enumerate(rules or [])
        for key, value in iterable:
            if isinstance(value, QualityRule):
                rule = value
            elif isinstance(value, Mapping):
                payload = dict(value)
                payload.setdefault("identifier", str(key))
                rule = QualityRule(**payload)
            else:
                raise ValueError(
                    "Quality rules must be mappings or QualityRule instances"
                )
            if rule.identifier in normalised:
                raise ValueError(f"Duplicate quality rule identifier: {rule.identifier}")
            normalised[rule.identifier] = rule
        return normalised

    @staticmethod
    def _normalise_contextual_requirements(
        requirements: Mapping[str, Any] | Iterable[Any]
    ) -> Dict[str, ContextualRequirement]:
        normalised: Dict[str, ContextualRequirement] = {}
        if isinstance(requirements, Mapping):
            iterable = requirements.items()
        else:
            iterable = enumerate(requirements or [])
        for key, value in iterable:
            if isinstance(value, ContextualRequirement):
                requirement = value
            elif isinstance(value, Mapping):
                payload = dict(value)
                payload.setdefault("identifier", str(key))
                requirement = ContextualRequirement(**payload)
            elif isinstance(value, bool):
                requirement = ContextualRequirement(
                    identifier=str(key),
                    description=f"Requirement flag for {key}",
                    enabled=value,
                )
            else:
                raise ValueError(
                    "Contextual requirements must be mappings, booleans, or ContextualRequirement instances"
                )
            if requirement.identifier in normalised:
                raise ValueError(
                    f"Duplicate contextual requirement identifier: {requirement.identifier}"
                )
            normalised[requirement.identifier] = requirement
        return normalised

    @staticmethod
    def _normalise_factual_rules(
        rules: Mapping[str, Any] | Iterable[Any]
    ) -> Dict[str, FactualVerificationRule]:
        normalised: Dict[str, FactualVerificationRule] = {}
        if isinstance(rules, Mapping):
            iterable = rules.items()
        else:
            iterable = enumerate(rules or [])
        for key, value in iterable:
            if isinstance(value, FactualVerificationRule):
                rule = value
            elif isinstance(value, Mapping):
                payload = dict(value)
                payload.setdefault("identifier", str(key))
                rule = FactualVerificationRule(**payload)
            elif isinstance(value, bool):
                rule = FactualVerificationRule(
                    identifier=str(key),
                    description=f"Verification flag for {key}",
                    enabled=value,
                )
            else:
                raise ValueError(
                    "Factual verification rules must be mappings, booleans, or FactualVerificationRule instances"
                )
            if rule.identifier in normalised:
                raise ValueError(f"Duplicate factual verification identifier: {rule.identifier}")
            normalised[rule.identifier] = rule
        return normalised

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ValidationStandards":
        """Create a ``ValidationStandards`` instance from a raw mapping payload."""

        if not isinstance(payload, Mapping):
            raise ValueError("Validation standards payload must be a mapping")
        quality_rules = payload.get("quality_rules", {})
        contextual = payload.get("contextual_requirements", {})
        factual = payload.get("factual_verification", {})
        metadata = payload.get("metadata", {})
        return cls(
            article_type=payload.get("article_type", "unknown"),
            version=payload.get("version", "1.0"),
            quality_rules=quality_rules,
            contextual_requirements=contextual,
            factual_verification=factual,
            metadata=metadata,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialise standards into a JSON-compatible dictionary."""

        return {
            "article_type": self.article_type,
            "version": self.version,
            "quality_rules": {key: rule.to_dict() for key, rule in self.quality_rules.items()},
            "contextual_requirements": {
                key: requirement.to_dict()
                for key, requirement in self.contextual_requirements.items()
            },
            "factual_verification": {
                key: rule.to_dict() for key, rule in self.factual_verification.items()
            },
            "metadata": self.metadata,
        }

    def enabled_quality_rules(self) -> Iterable[QualityRule]:
        """Iterate over quality rules that are currently enabled."""

        return (rule for rule in self.quality_rules.values() if rule.enabled)

    def enabled_contextual_requirements(self) -> Iterable[ContextualRequirement]:
        """Iterate over contextual requirements that are currently enabled."""

        return (
            requirement
            for requirement in self.contextual_requirements.values()
            if requirement.enabled
        )

    def enabled_factual_rules(self) -> Iterable[FactualVerificationRule]:
        """Iterate over factual verification rules that are currently enabled."""

        return (rule for rule in self.factual_verification.values() if rule.enabled)
