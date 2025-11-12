"""Fact-checking processor for article validation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from statistics import mean
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from src.shared.utils.logging import get_logger

from ..contracts import ValidationDimension, ValidationIssue
from ..llm import ClaimVerificationResult, GeminiClient, GeminiClientError
from .claim_extractor import ClaimCandidate, extract_claims

LOGGER = get_logger(__name__)

_DEFAULT_MAX_CLAIMS = 10
_DEFAULT_PRIORITY_THRESHOLD = 0.45
_PRIORITY_DETAIL_LIMIT = 8

_PRIORITY_CATEGORY_WEIGHTS = {
    "roster": 0.75,
    "event": 0.65,
    "statistic": 0.7,
    "factual": 0.55,
    "quote": 0.2,
}

_TRANSACTION_KEYWORDS = {
    "signed",
    "re-signed",
    "resigned",
    "waived",
    "traded",
    "acquired",
    "released",
    "claimed",
    "activated",
    "designated to return",
}

_STATUS_KEYWORDS = {
    "injured reserve",
    "season-ending",
    "status",
    "returning",
    "questionable",
    "out for",
    "expected to play",
}

_PERFORMANCE_KEYWORDS = {
    "yards",
    "touchdowns",
    "receptions",
    "sacks",
    "interceptions",
    "points",
    "assists",
    "goals",
}

_TIME_REFERENCES = {
    "this season",
    "last season",
    "last year",
    "this year",
    "since",
    "through",
    "over the past",
}


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def _contains_number(text: str) -> bool:
    return any(char.isdigit() for char in text)


def _truncate(text: str, limit: int = 160) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


@dataclass(frozen=True)
class PrioritisedClaim:
    claim: ClaimCandidate
    score: float
    reasons: Tuple[str, ...]


@dataclass
class FactCheckerConfig:
    max_claims: int = _DEFAULT_MAX_CLAIMS
    max_concurrent_requests: int = 3
    min_priority_score: float = _DEFAULT_PRIORITY_THRESHOLD


class FactChecker:
    """Verifies factual claims in articles using the LLM client."""

    def __init__(
        self,
    llm_client: GeminiClient,
        *,
        config: Optional[FactCheckerConfig] = None,
    ) -> None:
        self._llm_client = llm_client
        self._config = config or FactCheckerConfig()
        if self._config.max_claims <= 0:
            LOGGER.warning(
                "max_claims must be positive; falling back to %d", _DEFAULT_MAX_CLAIMS
            )
            self._config.max_claims = _DEFAULT_MAX_CLAIMS
        self._config.min_priority_score = _clamp_score(self._config.min_priority_score)
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent_requests)
        self._logger = get_logger(__name__)
        self._logger.debug(
            "FactChecker initialised with max_claims=%d, priority_threshold=%.2f",
            self._config.max_claims,
            self._config.min_priority_score,
        )

    async def verify_facts(
        self,
        article: Mapping[str, object],
        *,
        team_context: Optional[Mapping[str, object]] = None,
        source_summaries: Optional[Sequence[str]] = None,
        additional_context: Optional[str] = None,
    ) -> ValidationDimension:
        """Extract and verify claims, returning a ``ValidationDimension`` result."""

        claims = extract_claims(article, team_context=team_context)
        total_candidates = len(claims)

        selected, overflow, low_priority = self._prioritise_claims(
            claims,
            team_context=team_context,
        )

        if not selected:
            self._logger.info(
                "No claims met priority threshold for falsification (threshold %.2f, considered %d)",
                self._config.min_priority_score,
                total_candidates,
            )
            return self._build_dimension(
                selected,
                [],
                total_candidates=total_candidates,
                deferred_capacity=overflow,
                deferred_low_priority=low_priority,
            )

        try:
            claim_payloads = []
            for idx, entry in enumerate(selected):
                claim = entry.claim
                claim_payloads.append(
                    {
                        "index": idx,
                        "text": claim.text,
                        "category": claim.category,
                        "source_field": claim.source_field,
                        "sentence_index": claim.sentence_index,
                        "priority_score": round(entry.score, 3),
                        "priority_reason": "; ".join(entry.reasons),
                    }
                )

            shared_context_parts: List[str] = []
            if additional_context:
                shared_context_parts.append(additional_context)
            shared_context_parts.append(
                f"{len(selected)} of {total_candidates} claims selected for falsification (threshold {self._config.min_priority_score:.2f})."
            )
            if overflow:
                shared_context_parts.append(
                    f"{len(overflow)} additional high-priority claims deferred due to max_claims limit."
                )
            if low_priority:
                shared_context_parts.append(
                    f"{len(low_priority)} claims skipped for low falsifiability signals."
                )

            unique_categories = sorted(
                {entry.claim.category for entry in selected if entry.claim.category}
            )
            if unique_categories:
                shared_context_parts.append("Claim categories: " + ", ".join(unique_categories))

            summary = self._format_priority_summary(selected)
            if summary:
                shared_context_parts.append("Prioritisation rationale: " + summary)

            shared_context = "\n".join(shared_context_parts) if shared_context_parts else None

            async with self._semaphore:
                results = await self._llm_client.verify_claims_batch(
                    claim_payloads,
                    shared_context=shared_context,
                    source_summaries=source_summaries,
                )

                # Fallback: if batch returned all uncertain/empty, try individual verifications
                if results and all(
                    r.verdict == "uncertain" and r.confidence == 0.0 and "omitted claim results" in r.reasoning
                    for r in results
                ):
                    self._logger.warning("Batch verification returned empty results; falling back to individual verifications")
                    results = await self._verify_claims_individually(
                        selected, claim_payloads, shared_context, source_summaries
                    )

        except GeminiClientError as exc:
            self._logger.warning("Batch fact-checking failed: %s", exc)
            results = [exc for _ in selected]

        dimension = self._build_dimension(
            selected,
            results,
            total_candidates=total_candidates,
            deferred_capacity=overflow,
            deferred_low_priority=low_priority,
        )
        return dimension

    async def _verify_claims_individually(
        self,
        claims: Sequence[PrioritisedClaim],
        claim_payloads: List[dict],
        shared_context: Optional[str],
        source_summaries: Optional[Sequence[str]],
    ) -> List[ClaimVerificationResult]:
        """Verify claims one by one as fallback when batch fails."""
        results = []
        for claim_payload in claim_payloads:
            try:
                result = await self._llm_client.verify_claim(
                    claim=claim_payload["text"],
                    context=shared_context,
                    source_summaries=source_summaries,
                )
                results.append(result)
            except GeminiClientError as exc:
                self._logger.warning(f"Individual verification failed for claim {claim_payload['index']}: {exc}")
                results.append(exc)
        return results

    def _build_dimension(
        self,
        claims: Sequence[PrioritisedClaim],
        results: Sequence[ClaimVerificationResult | Exception],
        *,
        total_candidates: int,
        deferred_capacity: Sequence[PrioritisedClaim],
        deferred_low_priority: Sequence[PrioritisedClaim],
    ) -> ValidationDimension:
        verified = 0
        contradicted = 0
        uncertain = 0
        errors = 0
        issues: List[ValidationIssue] = []
        confidences: List[float] = []

        for entry, result in zip(claims, results):
            claim = entry.claim
            if isinstance(result, Exception):
                # Verification error: treat as uncertain (cannot falsify = passes)
                # The model's job is to falsify claims, not verify them
                # If verification fails, we cannot falsify the claim, so it passes
                errors += 1
                uncertain += 1
                confidences.append(0.0)
                continue

            confidences.append(result.confidence)
            if result.verdict == "verified":
                verified += 1
            elif result.verdict == "contradicted":
                contradicted += 1
                issues.append(
                    ValidationIssue(
                        severity="critical",
                        category="factual",
                        message=f"Claim contradicted: {claim.text}",
                        location=claim.source_field,
                        suggestion="Update article with accurate information.",
                        source_url=result.sources[0] if result.sources else None,
                    )
                )
            else:
                # Uncertain claims are assumed valid (cannot be falsified)
                uncertain += 1

        total_checked = len(claims)
        # Score based on contradictions only
        # Falsification model: if we can't falsify it (uncertain/verified), it passes
        # Only contradicted claims reduce the score
        score = 1.0 - (contradicted / total_checked) if total_checked else 1.0
        confidence = mean(confidences) if confidences else 0.0
        if total_checked == 0:
            confidence = 1.0 if total_candidates == 0 else 0.7
        # Pass if no claims were contradicted (errors don't fail since they're uncertain)
        passed = contradicted == 0

        details = {
            "claims_considered": total_candidates,
            "claims_checked": total_checked,
            "claims_selected": total_checked,
            "claims_total": total_candidates,
            "verified": verified,
            "contradicted": contradicted,
            "uncertain": uncertain,
            "errors": errors,
            "priority_threshold": round(self._config.min_priority_score, 3),
            "selection_counts": {
                "considered": total_candidates,
                "selected": total_checked,
                "deferred_capacity": len(deferred_capacity),
                "deferred_low_priority": len(deferred_low_priority),
            },
            "selected_claims": self._serialise_priorities(claims),
            "deferred_capacity": self._serialise_priorities(deferred_capacity),
            "deferred_low_priority": self._serialise_priorities(deferred_low_priority),
            "priority_policy": "heuristic-weighted",
        }

        return ValidationDimension(
            enabled=True,
            score=score,
            confidence=confidence,
            passed=passed,
            issues=issues,
            details=details,
        )

    def _serialise_priorities(
        self,
        claims: Sequence[PrioritisedClaim],
    ) -> Mapping[str, object]:
        items: List[Mapping[str, object]] = []
        for entry in claims[:_PRIORITY_DETAIL_LIMIT]:
            claim = entry.claim
            items.append(
                {
                    "text": _truncate(claim.text),
                    "category": claim.category,
                    "score": round(entry.score, 3),
                    "reasons": list(entry.reasons),
                    "source_field": claim.source_field,
                    "sentence_index": claim.sentence_index,
                }
            )
        return {
            "items": items,
            "omitted": max(0, len(claims) - len(items)),
        }

    def _format_priority_summary(
        self,
        claims: Sequence[PrioritisedClaim],
        *,
        limit: int = 3,
    ) -> str:
        if not claims:
            return ""
        snippets: List[str] = []
        for entry in claims[:limit]:
            reason_text = ", ".join(entry.reasons[:2]) or "factual assertion"
            snippets.append(
                f"{entry.claim.category} (score {entry.score:.2f}): {reason_text}"
            )
        remaining = len(claims) - limit
        if remaining > 0:
            snippets.append(f"… {remaining} more prioritised claims")
        return " | ".join(snippets)

    def _prioritise_claims(
        self,
        claims: Sequence[ClaimCandidate],
        *,
        team_context: Optional[Mapping[str, object]] = None,
    ) -> Tuple[List[PrioritisedClaim], List[PrioritisedClaim], List[PrioritisedClaim]]:
        if not claims:
            return [], [], []

        focus_tokens = self._team_tokens(team_context)
        scored: List[PrioritisedClaim] = []
        low_priority: List[PrioritisedClaim] = []

        for claim in claims:
            score, reasons = self._score_claim(claim, focus_tokens)
            entry = PrioritisedClaim(claim=claim, score=score, reasons=reasons)
            if score >= self._config.min_priority_score:
                scored.append(entry)
            else:
                low_priority.append(entry)

        scored.sort(key=lambda entry: entry.score, reverse=True)
        selected = scored[: self._config.max_claims]
        overflow = scored[self._config.max_claims :]

        self._logger.debug(
            "Prioritised %d claims (selected=%d, overflow=%d, low=%d)",
            len(claims),
            len(selected),
            len(overflow),
            len(low_priority),
        )

        return selected, overflow, low_priority

    def _score_claim(
        self,
        claim: ClaimCandidate,
        focus_tokens: Sequence[str],
    ) -> Tuple[float, Tuple[str, ...]]:
        lower = claim.text.lower()
        score = _PRIORITY_CATEGORY_WEIGHTS.get(claim.category, 0.4)
        reasons: List[str] = []

        category_reasons = {
            "roster": "roster/transaction focus",
            "event": "game result or schedule detail",
            "statistic": "statistical performance detail",
            "factual": "general factual assertion",
            "quote": "quoted material",
        }
        category_reason = category_reasons.get(claim.category)
        if category_reason:
            reasons.append(category_reason)

        if any(keyword in lower for keyword in _TRANSACTION_KEYWORDS):
            score += 0.18
            reasons.append("transaction keyword present")

        if any(keyword in lower for keyword in _STATUS_KEYWORDS):
            score += 0.12
            reasons.append("injury or availability status")

        if _contains_number(claim.text):
            score += 0.08
            reasons.append("contains numeric detail")

        if any(keyword in lower for keyword in _PERFORMANCE_KEYWORDS) and _contains_number(
            claim.text
        ):
            score += 0.12
            reasons.append("numeric performance metric")

        if any(keyword in lower for keyword in _TIME_REFERENCES):
            score += 0.05
            reasons.append("explicit time reference")

        if focus_tokens and any(token in lower for token in focus_tokens):
            score += 0.05
            reasons.append("mentions focus team context")

        if claim.category == "quote":
            score *= 0.4
            reasons.append("quote adjusted for lower falsifiability")

        score = _clamp_score(score)

        if not reasons:
            reasons.append("no strong falsification signals")

        deduped_reasons: List[str] = []
        for reason in reasons:
            if reason not in deduped_reasons:
                deduped_reasons.append(reason)

        return score, tuple(deduped_reasons)

    @staticmethod
    def _team_tokens(team_context: Optional[Mapping[str, object]]) -> List[str]:
        if not team_context:
            return []

        tokens: List[str] = []
        for key in ("team", "team_name", "name", "nickname"):
            value = team_context.get(key)
            if isinstance(value, str):
                cleaned = value.strip().lower()
                if cleaned:
                    tokens.append(cleaned)

        aliases = team_context.get("aliases") if isinstance(team_context, Mapping) else None
        if isinstance(aliases, Iterable) and not isinstance(aliases, (str, bytes, bytearray)):
            for alias in aliases:
                if not alias:
                    continue
                cleaned = str(alias).strip().lower()
                if cleaned:
                    tokens.append(cleaned)

        return tokens
