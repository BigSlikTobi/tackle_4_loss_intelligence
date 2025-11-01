"""Decision engine for article validation outcomes."""

from __future__ import annotations

from typing import List, Tuple

from src.shared.utils.logging import get_logger

from ..config import ValidationConfig
from ..contracts import ValidationDimension, ValidationIssue

LOGGER = get_logger(__name__)


class DecisionEngine:
    """Derives release decisions from validation results and thresholds."""

    def __init__(self, config: ValidationConfig) -> None:
        self._config = config
        self._logger = get_logger(__name__)

    def make_decision(
        self,
        factual: ValidationDimension,
        contextual: ValidationDimension,
        quality: ValidationDimension,
    ) -> Tuple[str, bool, List[str], List[str]]:
        """Return decision tuple of (decision, is_releasable, rejection_reasons, review_reasons)."""

        rejection_reasons: List[str] = []
        review_reasons: List[str] = []

        critical_messages = self._collect_critical_issues(factual, contextual, quality)
        rejection_reasons.extend(critical_messages)
        
        # Collect warning-level issues for review (especially contextual issues)
        warning_messages = self._collect_warning_issues(factual, contextual, quality)
        review_reasons.extend(warning_messages)

        rejection_reasons.extend(
            self._threshold_failures(factual, self._config.factual_threshold, "factual accuracy")
        )
        rejection_reasons.extend(
            self._threshold_failures(
                contextual,
                self._config.contextual_threshold,
                "contextual accuracy",
            )
        )
        rejection_reasons.extend(
            self._threshold_failures(quality, self._config.quality_threshold, "quality standards")
        )

        review_reasons.extend(
            self._confidence_flags(
                factual,
                "factual accuracy",
                self._config.factual_threshold,
            )
        )
        review_reasons.extend(
            self._confidence_flags(
                contextual,
                "contextual accuracy",
                self._config.contextual_threshold,
            )
        )
        review_reasons.extend(
            self._confidence_flags(
                quality,
                "quality standards",
                self._config.quality_threshold,
            )
        )

        decision = "release"
        is_releasable = True

        if rejection_reasons:
            decision = "reject"
            is_releasable = False
        elif review_reasons:
            decision = "review_required"
            is_releasable = False

        self._logger.debug(
            "Decision computed",
            extra={
                "decision": decision,
                "rejection_reasons": rejection_reasons,
                "review_reasons": review_reasons,
            },
        )

        return decision, is_releasable, rejection_reasons, review_reasons

    def _collect_critical_issues(self, *dimensions: ValidationDimension) -> List[str]:
        reasons: List[str] = []
        for dimension in dimensions:
            if not dimension.enabled:
                continue
            for issue in dimension.issues:
                if issue.severity == "critical":
                    reasons.append(issue.message)
        return reasons

    def _collect_warning_issues(self, *dimensions: ValidationDimension) -> List[str]:
        """Collect warning-level issues from all dimensions for review."""
        reasons: List[str] = []
        for dimension in dimensions:
            if not dimension.enabled:
                continue
            for issue in dimension.issues:
                if issue.severity == "warning":
                    reasons.append(issue.message)
        return reasons

    def _threshold_failures(
        self,
        dimension: ValidationDimension,
        threshold: float,
        label: str,
    ) -> List[str]:
        if not dimension.enabled:
            return []

        reasons: List[str] = []
        if dimension.score < threshold:
            reasons.append(f"{label.title()} score {dimension.score:.2f} below threshold {threshold:.2f}.")
        elif not dimension.passed:
            reasons.append(f"{label.title()} checks did not pass across all requirements.")
        return reasons

    def _confidence_flags(
        self,
        dimension: ValidationDimension,
        label: str,
        threshold: float,
    ) -> List[str]:
        """Return confidence-based review flags only if no specific warnings exist."""
        if not dimension.enabled:
            return []
        if dimension.score < threshold or not dimension.passed:
            return []  # already captured by rejection

        # Don't add generic confidence messages - only specific issue messages are needed
        # Warning-level issues are collected separately via _collect_warning_issues()
        return []
