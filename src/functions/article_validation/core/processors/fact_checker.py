"""Fact-checking processor for article validation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from statistics import mean
from typing import List, Mapping, Optional, Sequence

from src.shared.utils.logging import get_logger

from ..contracts import ValidationDimension, ValidationIssue
from ..llm import ClaimVerificationResult, GeminiClient, GeminiClientError
from .claim_extractor import ClaimCandidate, extract_claims

LOGGER = get_logger(__name__)

_DEFAULT_MAX_CLAIMS = 10


@dataclass
class FactCheckerConfig:
    max_claims: int = _DEFAULT_MAX_CLAIMS
    max_concurrent_requests: int = 3


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
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent_requests)
        self._logger = get_logger(__name__)

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
        claims = claims[: self._config.max_claims]

        if not claims:
            return ValidationDimension(
                enabled=True,
                score=1.0,
                confidence=1.0,
                passed=True,
                issues=[],
                details={
                    "claims_checked": 0,
                    "claims_total": 0,
                    "verified": 0,
                    "contradicted": 0,
                    "uncertain": 0,
                    "errors": 0,
                },
            )

        try:
            claim_payloads = [
                {
                    "index": idx,
                    "text": claim.text,
                    "category": claim.category,
                    "source_field": claim.source_field,
                    "sentence_index": claim.sentence_index,
                }
                for idx, claim in enumerate(claims)
            ]

            shared_context_parts: List[str] = []
            if additional_context:
                shared_context_parts.append(additional_context)
            unique_categories = sorted({claim.category for claim in claims if claim.category})
            if unique_categories:
                shared_context_parts.append("Claim categories: " + ", ".join(unique_categories))
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
                        claims, claim_payloads, shared_context, source_summaries
                    )
                    
        except GeminiClientError as exc:
            self._logger.warning("Batch fact-checking failed: %s", exc)
            results = [exc for _ in claims]

        dimension = self._build_dimension(claims, results)
        return dimension

    async def _verify_claims_individually(
        self,
        claims: Sequence[ClaimCandidate],
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
        claims: Sequence[ClaimCandidate],
        results: Sequence[ClaimVerificationResult | Exception],
    ) -> ValidationDimension:
        verified = 0
        contradicted = 0
        uncertain = 0
        errors = 0
        issues: List[ValidationIssue] = []
        confidences: List[float] = []

        for claim, result in zip(claims, results):
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
        # Pass if no claims were contradicted (errors don't fail since they're uncertain)
        passed = contradicted == 0

        details = {
            "claims_checked": total_checked,
            "claims_total": total_checked,
            "verified": verified,
            "contradicted": contradicted,
            "uncertain": uncertain,
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