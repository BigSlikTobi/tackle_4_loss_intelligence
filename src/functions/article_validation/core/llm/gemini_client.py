"""Async Gemini client wrapper with Google Search grounding support."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from textwrap import dedent
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError, ResourceExhausted

from src.shared.utils.logging import get_logger

from ..config import LLMConfig
from .rate_limiter import RateLimitExceeded, RateLimiter

LOGGER = get_logger(__name__)

_MAX_CONTEXT_CHARS = 12000
_JSON_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
_RETRY_DELAY_PATTERN = re.compile(r"retry in ([0-9.]+)s", re.IGNORECASE)
_DEFAULT_TEMPERATURE = 0.1
_MAX_OUTPUT_TOKENS = 4096
_MAX_CLAIMS_PER_BATCH = 5
_SUPPORTED_MODELS = frozenset()


class GeminiClientError(RuntimeError):
    """Raised when Gemini operations fail."""


@dataclass
class ClaimVerificationResult:
    """Structured result for claim verification."""

    claim: str
    verdict: str = "uncertain"
    confidence: float = 0.0
    reasoning: str = ""
    sources: List[str] = field(default_factory=list)
    raw_response: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim": self.claim,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "sources": list(self.sources),
            "raw_response": self.raw_response,
        }


@dataclass
class QualityRuleEvaluation:
    """Structured result for a quality rule evaluation."""

    rule_id: str
    passed: bool
    confidence: float
    rationale: str
    citations: List[str] = field(default_factory=list)
    raw_response: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "passed": self.passed,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "citations": list(self.citations),
            "raw_response": self.raw_response,
            "metadata": dict(self.metadata),
        }


class GeminiClient:
    """Thin async wrapper around Gemini with Google Search grounding."""

    def __init__(
        self,
        config: LLMConfig,
        *,
        rate_limiter: Optional[RateLimiter] = None,
    ) -> None:
        self.config = config
        self._logger = get_logger(__name__)
        genai.configure(api_key=config.api_key)
        self._rate_limiter = rate_limiter or RateLimiter(max_requests_per_minute=100)
        self._request_timeout = config.timeout_seconds

    async def verify_claim(
        self,
        claim: str,
        *,
        context: Optional[str] = None,
        source_summaries: Optional[Sequence[str]] = None,
    ) -> ClaimVerificationResult:
        results = await self.verify_claims_batch(
            [
                {
                    "index": 0,
                    "text": claim,
                    "category": None,
                    "source_field": None,
                    "sentence_index": 0,
                }
            ],
            shared_context=context,
            source_summaries=source_summaries,
        )
        return results[0]

    async def verify_claims_batch(
        self,
        claims: Sequence[Mapping[str, Any]],
        *,
        shared_context: Optional[str] = None,
        source_summaries: Optional[Sequence[str]] = None,
    ) -> List[ClaimVerificationResult]:
        if not claims:
            return []

        for claim in claims:
            text = claim.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Each claim must include non-empty `text`.")

        if len(claims) > _MAX_CLAIMS_PER_BATCH:
            self._logger.info(f"Splitting {len(claims)} claims into batches of {_MAX_CLAIMS_PER_BATCH}")
            all_results = []
            for i in range(0, len(claims), _MAX_CLAIMS_PER_BATCH):
                batch = claims[i:i + _MAX_CLAIMS_PER_BATCH]
                self._logger.debug(f"Processing batch {i // _MAX_CLAIMS_PER_BATCH + 1} with {len(batch)} claims")
                batch_results = await self._verify_single_batch(batch, shared_context, source_summaries)
                all_results.extend(batch_results)
            return all_results

        return await self._verify_single_batch(claims, shared_context, source_summaries)

    async def _verify_single_batch(
        self,
        claims: Sequence[Mapping[str, Any]],
        shared_context: Optional[str],
        source_summaries: Optional[Sequence[str]],
    ) -> List[ClaimVerificationResult]:
        prompt = self._build_claims_batch_prompt(claims, shared_context, source_summaries)
        response_text = await self._invoke_model(prompt, allow_web_search=True)
        self._logger.debug(f"Received response for batch of {len(claims)} claims, length: {len(response_text)}")
        return self._parse_claims_batch_response(claims, response_text)

    async def evaluate_quality_rule(
        self,
        article_text: str,
        rule: Mapping[str, Any] | Any,
    ) -> QualityRuleEvaluation:
        rule_payload = self._normalise_rule(rule)
        prompt = self._build_quality_prompt(article_text, rule_payload)
        response_text = await self._invoke_model(prompt, allow_web_search=True)
        return self._parse_quality_response(rule_payload, response_text)

    async def aclose(self) -> None:
        return None

    async def run_prompt(
        self,
        prompt: List[Dict[str, Any]],
        *,
        allow_web_search: Optional[bool] = False,
    ) -> str:
        return await self._invoke_model(prompt, allow_web_search=allow_web_search)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _invoke_model(
        self,
        prompt: List[Dict[str, Any]],
        *,
        allow_web_search: Optional[bool] = None,
    ) -> str:
        use_web_search = self.config.enable_web_search if allow_web_search is None else bool(allow_web_search)
        system_text, user_text = self._separate_prompt(prompt)
        if not user_text:
            user_text = "(no user content provided)"

        # Build generation config
        generation_config = {
            "temperature": _DEFAULT_TEMPERATURE,
            "max_output_tokens": _MAX_OUTPUT_TOKENS,
        }

        # Build tools for grounding if needed
        tools = None
        if use_web_search:
            tools = [{"google_search_retrieval": {}}]

        prompt_text = user_text.strip()
        if system_text:
            prompt_text = f"{system_text.strip()}\n\n{prompt_text}".strip()
        if not prompt_text:
            prompt_text = "(no content provided)"

        max_attempts = 3
        attempt = 0
        last_rate_exc: Optional[ResourceExhausted] = None

        while attempt < max_attempts:
            attempt += 1
            try:
                await self._rate_limiter.acquire(timeout=self._request_timeout)
            except RateLimitExceeded as exc:
                self._logger.warning("Local rate limiter timed out waiting for available quota")
                raise GeminiClientError("Local rate limiter exhausted") from exc

            try:
                model = genai.GenerativeModel(
                    model_name=self.config.model,
                    generation_config=generation_config,
                )
                
                # Add tools if grounding is enabled
                if tools:
                    model = genai.GenerativeModel(
                        model_name=self.config.model,
                        generation_config=generation_config,
                        tools=tools,
                    )
                
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        model.generate_content,
                        prompt_text,
                    ),
                    timeout=self._request_timeout,
                )

                if hasattr(response, 'candidates') and response.candidates:
                    first_candidate = response.candidates[0]
                    if hasattr(first_candidate, 'finish_reason'):
                        self._logger.debug(f"Finish reason: {first_candidate.finish_reason}")

                text = ""
                try:
                    if hasattr(response, 'text'):
                        text = response.text or ""
                except Exception as e:
                    self._logger.warning(f"Error accessing response.text: {e}")
                    if hasattr(response, 'candidates') and response.candidates:
                        first_candidate = response.candidates[0]
                        if hasattr(first_candidate, 'content') and hasattr(first_candidate.content, 'parts'):
                            parts = first_candidate.content.parts
                            if parts and hasattr(parts[0], 'text'):
                                text = parts[0].text or ""

                if not text:
                    self._logger.debug("Empty response (finish_reason may indicate why)")

                return text

            except ResourceExhausted as exc:
                self._logger.warning("Gemini rate limit reached: %s", exc)
                self._rate_limiter.release()
                last_rate_exc = exc
                if attempt >= max_attempts:
                    raise GeminiClientError("Gemini rate limit reached") from exc
                await asyncio.sleep(self._retry_delay_from_exception(exc, attempt))
                continue
            except GoogleAPIError as exc:
                self._logger.warning("Gemini API error: %s", exc)
                self._rate_limiter.release()
                raise GeminiClientError("Gemini API error") from exc
            except asyncio.TimeoutError as exc:
                self._logger.warning("Gemini request timed out after %.1fs", self._request_timeout)
                self._rate_limiter.release()
                raise GeminiClientError("Gemini request timed out") from exc
            except Exception as exc:  # pragma: no cover
                self._logger.exception("Unexpected Gemini failure")
                self._rate_limiter.release()
                raise GeminiClientError("Unexpected Gemini failure") from exc

        if last_rate_exc is not None:
            raise GeminiClientError("Gemini rate limit reached") from last_rate_exc
        raise GeminiClientError("Gemini request failed without specific error")

    @staticmethod
    def _separate_prompt(prompt: List[Dict[str, Any]]) -> tuple[str, str]:
        system_parts: List[str] = []
        user_parts: List[str] = []
        for entry in prompt:
            content = str(entry.get("content", ""))
            if not content:
                continue
            role = entry.get("role")
            if role == "system":
                system_parts.append(content.strip())
            else:
                user_parts.append(content.strip())
        return "\n\n".join(system_parts), "\n\n".join(user_parts)

    def _build_claims_batch_prompt(
        self,
        claims: Sequence[Mapping[str, Any]],
        shared_context: Optional[str],
        summaries: Optional[Sequence[str]],
    ) -> List[Dict[str, Any]]:
        claims_payload = [
            {
                "index": int(claim.get("index", idx)),
                "text": str(claim.get("text", "")).strip(),
                "category": claim.get("category"),
                "source_field": claim.get("source_field"),
                "sentence_index": claim.get("sentence_index"),
            }
            for idx, claim in enumerate(claims)
        ]

        self._logger.debug(f"Building batch prompt for {len(claims_payload)} claims")

        context_text = (
            shared_context.strip()
            if isinstance(shared_context, str) and shared_context.strip()
            else "(none provided)"
        )
        summary_text = "\n".join(filter(None, (summaries or [])))

        instructions = dedent(
            """
            Review these NFL claims and attempt to FALSIFY them using your knowledge.

            ⚠️  YOUR TRAINING DATA HAS A CUTOFF DATE - YOU DON'T KNOW RECENT NEWS!
            Any contract extensions, trades, or signings from recent months are NOT in your knowledge.
            If you can't find information, that means YOUR DATA IS OUTDATED, not that it's false!

            🔴 CRITICAL RULE: "contradicted" ONLY if you have PROOF it's FALSE

            You MUST have CONTRADICTORY EVIDENCE to mark "contradicted":
              ✅ "Player X plays for Team A" when you KNOW they're on Team B → "contradicted"
              ✅ "QB Tom Brady is active" when you KNOW he retired → "contradicted"
              ✅ "This game happened on Sunday" when you KNOW it was Monday → "contradicted"

            You MUST mark "uncertain" if you just can't find information:
              ❌ "I don't see this contract in my data" → "uncertain" (NOT "contradicted")
              ❌ "I can't find this extension reported" → "uncertain" (NOT "contradicted")
              ❌ "No news sources mention this" → "uncertain" (NOT "contradicted")
              ❌ "This wasn't reported" → "uncertain" (NOT "contradicted")

            THESE PHRASES MEAN YOU SHOULD USE "uncertain":
              - "has not signed" (when you just can't find it)
              - "has not been reported"
              - "no credible sources"
              - "I don't have information about"
              - "not found in my knowledge"
              - "no evidence of"

            EXAMPLE 1 - Recent News (Contract):
              Claim: "Wide receiver signed a 3-year extension last month"
              ✅ RIGHT: "uncertain" - "Recent contract news may be outside training data"

            EXAMPLE 2 - Game-by-Game Details:
              Claim: "Team was 6-2 entering their bye week"
              ✅ RIGHT: "uncertain" - "Cannot verify specific week-by-week record progression"

            EXAMPLE 3 - Performance Assessment:
              Claim: "Linebacker has been a crucial part of the defense this season"
              ✅ RIGHT: "verified" - "This is a subjective assessment, not a falsifiable claim"

            ⚠️  BE HUMBLE ABOUT YOUR KNOWLEDGE GAPS:
              - You don't have complete week-by-week records for all teams
              - You don't know recent news (contracts, trades, injuries)
              - You don't have perfect recall of every mid-season statistic
              - When uncertain, default to "uncertain" (NOT "contradicted")

            VERDICT DECISION TREE:
              1) Provably false with contradictory evidence? → "contradicted"
              2) Confirmable true OR subjective/non-falsifiable? → "verified"
              3) Everything else / incomplete data → "uncertain" (DEFAULT)

            ENTITY CONTEXT POLICY:
              - Mentions of non-focus teams do not imply a claim is false if they appear as:
                trade/transaction counterparties (“acquired from”, “traded to”, “waived by”, “claimed from”),
                opponents (vs/at/beat/lost to),
                past affiliations (“formerly with”, “previously played for”),
                or locations/divisions/stadiums.
              - Do NOT mark “contradicted” solely due to such mentions.

            TRANSACTION & TENSE:
              - If the claim describes a transaction (“acquired/traded/signed from Team B”), treat Team B as a counterparty.
              - Only mark “contradicted” for a present-tense roster assertion (“X is on Team A”) when you have contradictory evidence
                for the stated time window; otherwise default to “uncertain”.

            Return JSON: {"claims": [{"index": 0, "verdict": "uncertain", "confidence": 0.5, "reasoning": "brief explanation", "sources": []}]}

            CLAIMS TO REVIEW:
            """
        ).strip()

        claims_list = "\n".join([f"{i}. {claim['text']}" for i, claim in enumerate(claims_payload)])
        focus_hint = "Focus Team (if present in context) refers to the subject team. Other team names may appear in non-focus roles."
        user_content = f"{instructions}\n\n{focus_hint}\n\n{claims_list}\n\nContext: {context_text}"

        self._logger.debug("Claims prompt preview: %s", user_content[:500])

        return [
            {
                "role": "system",
                "content": (
                    "You are an NFL fact-checker. Only flag FACTUAL ERRORS (wrong names, teams, stats). "
                    "Do NOT flag opinions or subjective assessments. Apply the Entity Context Policy."
                ),
            },
            {"role": "user", "content": user_content},
        ]

    @staticmethod
    def _build_quality_prompt(
        article_text: str,
        rule: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Quality validator with strengthened Entity Context Policy:
        - Outbound transactions (departures) are valid focus for the source team.
        - Inbound transactions (acquisitions) are valid focus for the acquiring team.
        - Opponent/fixture, past-team, and location mentions are non-focus roles (not penalized).
        - Tight 'JSON ONLY' guard to reduce 'not valid JSON' failures.
        """
        description = rule.get("description", "")
        identifier = rule.get("identifier", "quality_rule")
        severity = rule.get("severity", "warning")
        prompt_override = rule.get("prompt")

        guidance = prompt_override or "Assess compliance with the rule using the article content."
        metadata = rule.get("metadata") or {}
        focus_team = metadata.get("focus_team")
        focus_line = f"Focus Team: {focus_team}" if focus_team else "Focus Team: (not provided)"

        truncated_article = _truncate(article_text, _MAX_CONTEXT_CHARS)

        payload = dedent(
            f"""
            You evaluate generated sports journalism for quality.

            >>> OUTPUT REQUIREMENT: Respond with **ONLY** a single JSON object. No preamble, no explanation outside JSON.

            ## Task
            Decide if the article complies with the rule below, applying the **Entity Context Policy** and **Focus Validity Matrix**.

            **Entity Context Policy**
            - The **focus team** is the team under evaluation (e.g., if rule is for NYJ, the focus team is the New York Jets).
            - Mentions of other teams/entities are acceptable in **non-focus roles**:
              • Trade/transaction counterparties: “acquired X **from** Team B”, “traded X **to** Team B”, “claimed from waivers”.
              • Opponents/fixtures: “vs Team B”, “at Team B”, “beat/lost to Team B”.
              • Past affiliations: “formerly with Team B”, “previously played for Team B”, “waived by Team B”.
              • Locations/venues/divisions: cities, stadiums, conferences, divisions.

            **Focus Validity Matrix (CRITICAL)**
              - “Team A acquired Player X **from** Team B”  → Valid focus for **Team A** (inbound); Team B is counterparty (non-focus).
              - “Team A traded/sent Player X **to** Team B” → Valid focus for **Team A** (outbound); Team B is counterparty (non-focus).
              - “Team A waived/released Player X”          → Valid focus for **Team A** (outbound).
              - “Team A vs/at Team B”                      → Valid focus for **Team A** (opponent mention allowed).
              - “Player X formerly with Team B”            → Valid focus for current subject team; Team B is past_team (non-focus).

            **Tense & Time Heuristic**
              - Present-tense roster assertions (“X **is** a <Team> player”) must be judged in the timeframe **stated or implied**.
              - Transaction events are **point-in-time**; past-team mentions do not switch focus.
              - When news may be recent/contested and you cannot verify definitively, do **not** infer contradiction solely from absence; prefer **uncertain**.

            **Rumor/Correction Handling**
              - If the article clearly frames a *report/rumor* or *subsequent correction* (“reportedly”, “per”, “initially reported”, “later corrected”),
                judge focus by the **story’s subject (the focus team’s action/impact)**, not by the destination team’s identity.
              - Conflicting reports ≠ focus error. Only fail focus if the piece is actually about another team.

            What to return (STRICT JSON):
              {{
                "passed": <bool>,
                "confidence": <float 0..1>,
                "rationale": "<one or two sentences referencing the article and the policy>",
                "citations": ["<short quote from article>", "<URL or bullet if applicable>"]
              }}

            Rule ID: {identifier}
            Rule Description: {description}
            Rule Severity: {severity}
            Additional Guidance: {guidance}
            {focus_line}

            Article Content:
            {truncated_article}
            """
        ).strip()

        return [
            {"role": "system", "content": "You are a rigorous editorial quality reviewer. Output must be JSON only."},
            {"role": "user", "content": payload},
        ]

    @staticmethod
    def _normalise_rule(rule: Mapping[str, Any] | Any) -> Dict[str, Any]:
        if isinstance(rule, Mapping):
            return dict(rule)
        payload = {
            "identifier": getattr(rule, "identifier", "quality_rule"),
            "description": getattr(rule, "description", ""),
            "severity": getattr(rule, "severity", "warning"),
            "weight": getattr(rule, "weight", 1.0),
            "prompt": getattr(rule, "prompt", None),
        }
        metadata = getattr(rule, "metadata", None)
        if isinstance(metadata, Mapping):
            payload["metadata"] = dict(metadata)
        return payload

    def _parse_claims_batch_response(
        self,
        claims: Sequence[Mapping[str, Any]],
        response_text: str,
    ) -> List[ClaimVerificationResult]:
        data = self._extract_json(response_text)
        if not isinstance(data, Mapping):
            self._logger.warning("Batch fact-check response missing JSON payload; marking all claims uncertain")
            return [
                ClaimVerificationResult(
                    claim=str(claim.get("text", "")),
                    verdict="uncertain",
                    confidence=0.0,
                    reasoning="Model response was not valid JSON",
                    raw_response=response_text,
                )
                for claim in claims
            ]

        entries = data.get("claims")
        if not isinstance(entries, list):
            self._logger.warning("Batch fact-check response missing 'claims' list; marking all uncertain")
            return [
                ClaimVerificationResult(
                    claim=str(claim.get("text", "")),
                    verdict="uncertain",
                    confidence=0.0,
                    reasoning="Model response omitted claim results",
                    raw_response=response_text,
                )
                for claim in claims
            ]

        entry_by_index: Dict[int, Mapping[str, Any]] = {}
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            try:
                idx = int(entry.get("index"))
            except (TypeError, ValueError):
                continue
            entry_by_index[idx] = entry

        results: List[ClaimVerificationResult] = []
        for default_index, claim in enumerate(claims):
            entry = entry_by_index.get(int(claim.get("index", default_index)))
            claim_text = str(claim.get("text", ""))
            if not entry:
                results.append(
                    ClaimVerificationResult(
                        claim=claim_text,
                        verdict="uncertain",
                        confidence=0.0,
                        reasoning="No result returned for this claim",
                        raw_response=response_text,
                    )
                )
                continue

            verdict = str(entry.get("verdict", "uncertain")).strip().lower()
            if verdict not in {"verified", "contradicted", "uncertain"}:
                verdict = "uncertain"

            confidence = _clamp_float(entry.get("confidence", 0.0))
            reasoning = str(entry.get("reasoning", "")).strip()

            raw_sources = self._normalise_sources(entry.get("sources"))
            sources = [source for source in raw_sources if _is_allowed_source(source)]

            if verdict == "verified" and not sources:
                verdict = "uncertain"
                reasoning = (reasoning + " Citation missing from allowed sources.").strip()

            results.append(
                ClaimVerificationResult(
                    claim=claim_text,
                    verdict=verdict,
                    confidence=confidence,
                    reasoning=reasoning,
                    sources=sources,
                    raw_response=response_text,
                )
            )

        return results

    def _parse_quality_response(
        self,
        rule: Mapping[str, Any],
        response_text: str,
    ) -> QualityRuleEvaluation:
        data = self._extract_json(response_text)
        if not data:
            self._logger.warning(
                "Unable to parse quality rule response for %s; defaulting to failure",
                rule.get("identifier", "quality_rule"),
            )
            return QualityRuleEvaluation(
                rule_id=str(rule.get("identifier", "quality_rule")),
                passed=False,
                confidence=0.0,
                rationale="Model response was not valid JSON",
                raw_response=response_text,
            )

        passed = bool(data.get("passed", False))
        confidence = _clamp_float(data.get("confidence", 0.0))
        rationale = str(data.get("rationale", "")).strip()
        citations = self._normalise_sources(data.get("citations"))

        return QualityRuleEvaluation(
            rule_id=str(rule.get("identifier", "quality_rule")),
            passed=passed,
            confidence=confidence,
            rationale=rationale,
            citations=citations,
            raw_response=response_text,
            metadata=dict(rule.get("metadata", {})),
        )

    @staticmethod
    def _normalise_sources(value: Any) -> List[str]:
        if not value:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, Iterable):
            cleaned: List[str] = []
            for item in value:
                if not item:
                    continue
                text = str(item).strip()
                if text:
                    cleaned.append(text)
            return cleaned
        return []

    def _extract_json(self, raw_text: str) -> Dict[str, Any]:
        if not raw_text:
            return {}
        raw_text = raw_text.strip()

        # Remove markdown code blocks if present
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:].lstrip()
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:].lstrip()
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3].rstrip()
        raw_text = raw_text.strip()

        if not raw_text:
            self._logger.debug("After stripping markdown, no JSON content remained")
            return {}

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as e:
            self._logger.debug(f"Initial JSON parse failed: {e}. Trying regex fallback...")
            match = _JSON_PATTERN.search(raw_text)
            if not match:
                self._logger.debug(f"No JSON found via regex. First 200 chars: {raw_text[:200]}")
                return {}
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as e2:
                self._logger.debug(f"Regex-extracted JSON also failed: {e2}")
                return {}

    @staticmethod
    def _retry_delay_from_exception(exc: ResourceExhausted, attempt: int) -> float:
        text = str(exc)
        match = _RETRY_DELAY_PATTERN.search(text)
        if match:
            try:
                value = float(match.group(1))
                if value > 0:
                    return min(max(value, 0.5), 10.0)
            except ValueError:
                pass
        return min(5.0, 1.5 * attempt)


def _truncate(text: str, limit: int) -> str:
    if not isinstance(text, str):
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[TRUNCATED]"


def _clamp_float(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


def _is_allowed_source(url: str) -> bool:
    if not isinstance(url, str):
        return False
    lowered = url.lower()
    return "nfl.com" in lowered or "espn.com" in lowered
