"""Quality standards validation for generated articles."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from src.shared.utils.logging import get_logger

from ..contracts import ValidationDimension, ValidationIssue
from ..contracts.validation_standards import QualityRule, ValidationStandards
from ..llm import GeminiClient, GeminiClientError, QualityRuleEvaluation

LOGGER = get_logger(__name__)

_DEFAULT_MAX_CONCURRENCY = 3

_ARTICLE_TYPE_TO_MODULE = {
    "team_article": "team_article_generation",
}


@dataclass
class QualityValidatorConfig:
    max_concurrent_requests: int = _DEFAULT_MAX_CONCURRENCY


class QualityValidator:
    """Evaluates article quality against configured standards."""

    def __init__(
        self,
    llm_client: GeminiClient,
        *,
        config: Optional[QualityValidatorConfig] = None,
    ) -> None:
        self._llm_client = llm_client
        self._config = config or QualityValidatorConfig()
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent_requests)
        self._logger = get_logger(__name__)

    async def validate_quality(
        self,
        article: Mapping[str, Any] | str,
        *,
        standards: Optional[ValidationStandards | Mapping[str, Any]] = None,
        article_type: str = "unknown",
    ) -> ValidationDimension:
        resolved_standards = resolve_quality_standards(article_type, override=standards)
        rules = list(resolved_standards.enabled_quality_rules())

        if not rules:
            return ValidationDimension(
                enabled=True,
                score=1.0,
                confidence=1.0,
                passed=True,
                issues=[],
                details={
                    "rules_checked": 0,
                    "violations": 0,
                    "errors": 0,
                },
            )

        article_text = _article_to_text(article)
        if not article_text.strip():
            return ValidationDimension(
                enabled=True,
                score=0.0,
                confidence=0.0,
                passed=False,
                issues=[
                    ValidationIssue(
                        severity="warning",
                        category="quality",
                        message="Article contains no textual content for evaluation.",
                    )
                ],
                details={
                    "rules_checked": 0,
                    "violations": 0,
                    "errors": 0,
                },
            )

        evaluations = await self._evaluate_rules(article_text, rules)
        dimension = self._build_dimension(rules, evaluations)
        return dimension

    async def _evaluate_rules(
        self,
        article_text: str,
        rules: Sequence[QualityRule],
    ) -> List[QualityRuleEvaluation | Exception]:
        tasks = [self._evaluate_single(article_text, rule) for rule in rules]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _evaluate_single(
        self,
        article_text: str,
        rule: QualityRule,
    ) -> QualityRuleEvaluation:
        async with self._semaphore:
            try:
                return await self._llm_client.evaluate_quality_rule(
                    article_text,
                    rule.to_dict(),
                )
            except GeminiClientError as exc:
                self._logger.warning(
                    "Quality evaluation failed for rule %s: %s",
                    rule.identifier,
                    exc,
                )
                raise

    def _build_dimension(
        self,
        rules: Sequence[QualityRule],
        evaluations: Sequence[QualityRuleEvaluation | Exception],
    ) -> ValidationDimension:
        total_weight = sum(rule.weight for rule in rules)
        passed_weight = 0.0
        confidence_weight = 0.0
        violations = 0
        errors = 0
        issues: List[ValidationIssue] = []

        for rule, result in zip(rules, evaluations):
            if isinstance(result, Exception):
                errors += 1
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        category="quality",
                        message=f"Failed to evaluate quality rule: {rule.description}",
                        suggestion="Retry validation or review content manually.",
                    )
                )
                continue

            confidence_weight += result.confidence * rule.weight
            if result.passed:
                passed_weight += rule.weight
                continue

            violations += 1
            issues.append(
                ValidationIssue(
                    severity=rule.severity,
                    category="quality",
                    message=f"Quality rule failed ({rule.identifier}): {rule.description}",
                    suggestion=rule.metadata.get("suggestion")
                    if isinstance(rule.metadata, dict)
                    else "Revise the article to satisfy this standard.",
                    location=result.metadata.get("location")
                    if isinstance(result.metadata, dict)
                    else None,
                    source_url=_first_url(result.citations),
                )
            )

        score = passed_weight / total_weight if total_weight else 1.0
        confidence = confidence_weight / total_weight if total_weight else 0.0
        passed = violations == 0 and errors == 0

        details = {
            "rules_checked": len(rules),
            "violations": violations,
            "errors": errors,
        }

        return ValidationDimension(
            enabled=True,
            score=score,
            confidence=confidence,
            passed=passed,
            issues=issues,
            details=details,
        )


def resolve_quality_standards(
    article_type: str,
    *,
    override: Optional[ValidationStandards | Mapping[str, Any]] = None,
    base_path: Optional[Path] = None,
) -> ValidationStandards:
    """Resolve quality standards for the given article type."""

    if override is not None:
        return _coerce_standards(override, fallback_article_type=article_type)

    module_name = _ARTICLE_TYPE_TO_MODULE.get(article_type, None)
    if module_name:
        standards_path = _compute_standards_path(module_name, base_path=base_path)
        if standards_path is not None and standards_path.exists():
            try:
                with standards_path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                return ValidationStandards.from_dict(payload)
            except (OSError, json.JSONDecodeError) as exc:
                LOGGER.warning(
                    "Failed to load validation standards from %s: %s",
                    standards_path,
                    exc,
                )

    return _generic_standards(article_type)


def _compute_standards_path(module_name: str, *, base_path: Optional[Path] = None) -> Optional[Path]:
    if base_path is None:
        base_path = Path(__file__).resolve().parents[3]  # src/functions
    module_dir = base_path / module_name
    standards_path = module_dir / "validation_standards.json"
    return standards_path


def _coerce_standards(
    payload: ValidationStandards | Mapping[str, Any],
    *,
    fallback_article_type: str,
) -> ValidationStandards:
    if isinstance(payload, ValidationStandards):
        return payload
    if isinstance(payload, Mapping):
        data = dict(payload)
        data.setdefault("article_type", fallback_article_type)
        data.setdefault("version", "1.0")
        data.setdefault("contextual_requirements", {})
        data.setdefault("factual_verification", {})
        return ValidationStandards.from_dict(data)
    raise ValueError("quality standards override must be a mapping or ValidationStandards instance")


def _generic_standards(article_type: str) -> ValidationStandards:
    payload = {
        "article_type": article_type,
        "version": "1.0",
        "quality_rules": [
            {
                "identifier": "clarity",
                "description": "Article should clearly explain the most recent developments for the focus team.",
                "weight": 1.0,
                "severity": "warning",
            },
            {
                "identifier": "evidence",
                "description": "Claims should be grounded in verifiable information without speculation.",
                "weight": 1.0,
                "severity": "critical",
            },
        ],
        "contextual_requirements": {},
        "factual_verification": {},
    }
    return ValidationStandards.from_dict(payload)


def _article_to_text(article: Mapping[str, Any] | str) -> str:
    if isinstance(article, str):
        return article

    segments: List[str] = []

    def _collect(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            segments.append(value)
            return
        if isinstance(value, Mapping):
            for nested_value in value.values():
                _collect(nested_value)
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                _collect(item)

    _collect(article)
    return "\n".join(segment.strip() for segment in segments if segment.strip())


def _first_url(citations: Iterable[str]) -> Optional[str]:
    if not citations:
        return None
    for candidate in citations:
        if isinstance(candidate, str) and candidate.strip().lower().startswith("http"):
            return candidate.strip()
    return None