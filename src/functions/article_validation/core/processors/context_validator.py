"""Contextual accuracy validator for article validation."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from statistics import mean
from textwrap import dedent
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from src.shared.utils.logging import get_logger

from ..contracts import ValidationDimension, ValidationIssue
from ..llm import GeminiClient, GeminiClientError

LOGGER = get_logger(__name__)

_DEFAULT_MAX_ENTITIES = 12


@dataclass
class ContextValidatorConfig:
    max_entities: int = _DEFAULT_MAX_ENTITIES
    max_concurrent_requests: int = 3


@dataclass
class ContextualEntity:
    name: str
    category: str  # e.g. team, player, event
    evidence: Optional[str] = None


class ContextValidator:
    """Validates contextual focus of articles against team information."""

    def __init__(
        self,
    llm_client: GeminiClient,
        *,
        config: Optional[ContextValidatorConfig] = None,
    ) -> None:
        self._llm_client = llm_client
        self._config = config or ContextValidatorConfig()
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent_requests)
        self._logger = get_logger(__name__)

    async def validate_context(
        self,
        article: Mapping[str, object],
        *,
        team_context: Optional[Mapping[str, object]] = None,
        standards: Optional[Mapping[str, object]] = None,
    ) -> ValidationDimension:
        if not team_context:
            return ValidationDimension(
                enabled=True,
                score=0.0,
                confidence=0.0,
                passed=False,
                issues=[
                    ValidationIssue(
                        severity="warning",
                        category="contextual",
                        message="Team context not provided; unable to validate focus.",
                    )
                ],
                details={"entities_checked": 0},
            )

        extraction_prompt = self._build_extraction_prompt(article, team_context, standards)
        entities = await self._extract_entities(extraction_prompt)

        if not entities:
            return ValidationDimension(
                enabled=True,
                score=0.0,
                confidence=0.0,
                passed=False,
                issues=[
                    ValidationIssue(
                        severity="warning",
                        category="contextual",
                        message="No entities detected; article may lack contextual focus.",
                    )
                ],
                details={"entities_checked": 0},
            )

        verification_results = await self._verify_entities(entities, team_context)
        dimension = self._build_dimension(entities, verification_results, team_context)
        return dimension

    async def _extract_entities(self, prompt: List[Dict[str, str]]) -> List[ContextualEntity]:
        try:
            response_text = await self._llm_client.run_prompt(
                prompt,
                allow_web_search=True,
            )
        except GeminiClientError as exc:  # pragma: no cover
            self._logger.warning("Entity extraction failed: %s", exc)
            return []

        entities = self._parse_entities(response_text)
        return entities[: self._config.max_entities]

    async def _verify_entities(
        self,
        entities: Sequence[ContextualEntity],
        team_context: Mapping[str, object],
    ) -> List[Dict[str, object] | Exception]:
        tasks = [
            self._verify_single(entity, team_context)
            for entity in entities
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _verify_single(
        self,
        entity: ContextualEntity,
        team_context: Mapping[str, object],
    ) -> Dict[str, object]:
        async with self._semaphore:
            try:
                prompt = self._build_verification_prompt(entity, team_context)
                response_text = await self._llm_client.run_prompt(
                    prompt,
                    allow_web_search=True,
                )
                return self._parse_verification_response(entity, response_text)
            except GeminiClientError as exc:
                self._logger.warning(
                    "Entity verification failed for %s: %s",
                    entity.name,
                    exc,
                )
                raise

    def _build_dimension(
        self,
        entities: Sequence[ContextualEntity],
        results: Sequence[Dict[str, object] | Exception],
        team_context: Mapping[str, object],
    ) -> ValidationDimension:
        issues: List[ValidationIssue] = []
        scores: List[float] = []
        mismatches = 0
        errors = 0
        transaction_overrides: List[str] = []

        for entity, result in zip(entities, results):
            if isinstance(result, Exception):
                errors += 1
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        category="contextual",
                        message=f"Failed to verify entity context: {entity.name}",
                    )
                )
                continue

            parsed_result = dict(result)
            if not parsed_result.get("is_match", False) and self._should_accept_transaction(
                entity,
                parsed_result,
                team_context,
            ):
                parsed_result["is_match"] = True
                parsed_result["match_score"] = max(
                    float(parsed_result.get("match_score", 0.0)),
                    0.75,
                )
                message = str(parsed_result.get("message", ""))
                parsed_result["message"] = (
                    f"{message} (accepted due to transaction context)"
                    if message
                    else "Accepted due to transaction context."
                )
                transaction_overrides.append(entity.name)
                self._logger.debug(
                    "Accepted entity %s due to detected transaction context.",
                    entity.name,
                )

            match_score = float(parsed_result.get("match_score", 0.0))
            scores.append(match_score)
            if not parsed_result.get("is_match", False):
                mismatches += 1
                issues.append(
                    ValidationIssue(
                        severity="critical" if entity.category == "team" else "warning",
                        category="contextual",
                        message=parsed_result.get(
                            "message",
                            f"Entity does not align with focus team: {entity.name}",
                        ),
                        suggestion="Adjust article to focus on the specified team or correct the entity reference.",
                    )
                )

        total_entities = len(entities)
        score = 1.0 if total_entities == 0 else sum(scores) / (total_entities or 1)
        # Pass if score is acceptable, allowing for some mismatches/errors due to rate limits or outdated knowledge
        passed = score >= 0.70
        confidence = mean(scores) if scores else 0.0

        details = {
            "entities_checked": total_entities,
            "mismatches": mismatches,
            "errors": errors,
        }
        if transaction_overrides:
            details["transaction_overrides"] = transaction_overrides

        return ValidationDimension(
            enabled=True,
            score=score,
            confidence=confidence,
            passed=passed,
            issues=issues,
            details=details,
        )

    @staticmethod
    def _build_extraction_prompt(
        article: Mapping[str, object],
        team_context: Mapping[str, object],
        standards: Optional[Mapping[str, object]] = None,
    ) -> List[Dict[str, str]]:
        team_name = team_context.get("team_name") or team_context.get("team") or "the focus team"
        article_text = json.dumps(article, ensure_ascii=False)
        requirements = standards.get("contextual_requirements", {}) if standards else {}
        guidance = requirements.get(
            "guidance",
            "Identify referenced teams, players, and events with relevance to the focus team.",
        )

        user_content = dedent(
            f"""
            Extract referenced entities from the following article content.
            Focus team: {team_name}
            Guidance: {guidance}

            Respond strictly in JSON with keys:
              - entities: list of objects with keys name, category (team/player/event), evidence.

            Article Payload:
            {article_text}
            """
        ).strip()

        return [
            {"role": "system", "content": "You are an assistant that extracts sports entities."},
            {"role": "user", "content": user_content},
        ]

    @staticmethod
    def _build_verification_prompt(
        entity: ContextualEntity,
        team_context: Mapping[str, object],
    ) -> List[Dict[str, str]]:
        team_name = team_context.get("team_name") or team_context.get("team") or "the focus team"
        evidence = entity.evidence or "(no additional evidence provided)"

        system_content = dedent(
            """
            You verify contextual alignment for sports articles using a FALSIFICATION approach.
            
            CRITICAL INSTRUCTIONS:
            - Your job is to DISPROVE that an entity belongs to the focus team
            - ONLY mark is_match=false if you find CLEAR OBJECTIVE EVIDENCE the entity does NOT belong
            - When in doubt or evidence is unclear, mark is_match=true (assume it belongs)
            - DO NOT reject based on opinions, analysis, or narrative choices
            - DO NOT reject players/coaches just because your knowledge is outdated
            
            EXAMPLES OF WHAT TO REJECT (is_match=false):
            - Player clearly plays for a different team (with recent, verifiable evidence)
            - Event that has nothing to do with the focus team
            - Team name that is explicitly a different franchise
            
            EXAMPLES OF WHAT TO ACCEPT (is_match=true):
            - Player might have recently joined the team (your knowledge may be outdated)
            - Coach/coordinator mentioned in context of the focus team
            - Events discussed in relation to the focus team's situation
            - League-wide events mentioned for context
            - Former players discussed for historical context
            
            WARNING: Your knowledge cutoff may be outdated. If you're unsure about a player's current team,
            mark is_match=true and note the uncertainty in your message.
            """
        ).strip()

        user_content = dedent(
            f"""
            Determine whether the entity aligns with the focus team context.
            Focus team: {team_name}

            Entity:
              - name: {entity.name}
              - category: {entity.category}
              - evidence: {evidence}

            Respond strictly in JSON with keys:
              - is_match: boolean (false ONLY if you have clear evidence this does NOT belong)
              - match_score: float between 0 and 1 indicating confidence
              - message: short explanation of why it does/doesn't belong
            """
        ).strip()

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

    def _parse_entities(self, response_text: str) -> List[ContextualEntity]:
        if not response_text:
            return []
        
        # Strip markdown code blocks if present
        text = response_text.strip()
        if text.startswith("```json"):
            text = text[7:].lstrip()
        elif text.startswith("```"):
            text = text[3:].lstrip()
        if text.endswith("```"):
            text = text[:-3].rstrip()
        text = text.strip()
        
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            self._logger.warning("Failed to parse entity extraction JSON")
            return []

        items = payload.get("entities") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return []

        entities: List[ContextualEntity] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            category = str(item.get("category", "")).strip().lower() or "unknown"
            evidence = item.get("evidence")
            if name:
                entities.append(
                    ContextualEntity(name=name, category=category, evidence=evidence)
                )
        return entities

    def _parse_verification_response(
        self,
        entity: ContextualEntity,
        response_text: str,
    ) -> Dict[str, object]:
        if not response_text:
            return {
                "entity": entity.name,
                "is_match": False,
                "match_score": 0.0,
                "message": "Empty response from verification model.",
            }

        # Strip markdown code blocks if present
        text = response_text.strip()
        if text.startswith("```json"):
            text = text[7:].lstrip()
        elif text.startswith("```"):
            text = text[3:].lstrip()
        if text.endswith("```"):
            text = text[:-3].rstrip()
        text = text.strip()

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            self._logger.warning("Failed to parse verification JSON for %s", entity.name)
            return {
                "entity": entity.name,
                "is_match": False,
                "match_score": 0.0,
                "message": "Model response was not valid JSON.",
            }

        is_match = bool(payload.get("is_match", False))
        match_score = max(0.0, min(1.0, float(payload.get("match_score", 0.0))))
        message = str(payload.get("message", "")) or "No explanation provided."

        return {
            "entity": entity.name,
            "is_match": is_match,
            "match_score": match_score,
            "message": message,
        }

    def _should_accept_transaction(
        self,
        entity: ContextualEntity,
        result: Mapping[str, object],
        team_context: Mapping[str, object],
    ) -> bool:
        if entity.category not in {"player", "team", "coach"}:
            return False

        combined_text_parts = [
            str(result.get("message", "")),
            str(entity.evidence or ""),
        ]
        combined_text = " ".join(part for part in combined_text_parts if part).lower()
        if not combined_text:
            return False

        if not any(keyword in combined_text for keyword in _TRANSACTION_KEYWORDS):
            return False

        team_tokens = _team_tokens(team_context)
        if team_tokens and not any(token in combined_text for token in team_tokens):
            return False

        return True


def _team_tokens(team_context: Mapping[str, object]) -> List[str]:
    tokens: List[str] = []
    candidate_keys = (
        "team",
        "team_name",
        "name",
        "nickname",
        "team_id",
        "abbreviation",
    )

    for key in candidate_keys:
        value = team_context.get(key)
        if isinstance(value, str) and value.strip():
            tokens.append(value.strip().lower())

    aliases = team_context.get("aliases")
    if isinstance(aliases, Mapping):
        alias_values = aliases.values()
    else:
        alias_values = aliases

    if isinstance(alias_values, Iterable) and not isinstance(alias_values, (str, bytes, bytearray)):
        for alias in alias_values:
            if isinstance(alias, str) and alias.strip():
                tokens.append(alias.strip().lower())

    return list(dict.fromkeys(tokens))


_TRANSACTION_KEYWORDS = {
    "trade",
    "traded",
    "acquired",
    "acquire",
    "acquisition",
    "deal",
    "dealt",
    "package",
    "sent",
    "sending",
    "receive",
    "received",
    "swap",
    "exchanged",
    "exchange",
    "sign",
    "signed",
    "signing",
    "waive",
    "waived",
    "waiving",
    "release",
    "released",
    "releasing",
}
