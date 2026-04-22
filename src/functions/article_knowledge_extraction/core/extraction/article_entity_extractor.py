"""Article-level entity extraction via OpenAI (real-time, no Batch API)."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import List, Optional

import openai
from openai import APITimeoutError, OpenAIError, RateLimitError

from ..prompts import build_entity_prompt

logger = logging.getLogger(__name__)


_ALLOWED_TYPES = {"player", "team", "game", "staff"}


@dataclass
class ExtractedEntity:
    entity_type: str
    mention_text: str
    confidence: Optional[float] = None
    rank: Optional[int] = None
    position: Optional[str] = None
    team_abbr: Optional[str] = None
    team_name: Optional[str] = None


class ArticleEntityExtractor:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5.4-mini",
        timeout: int = 60,
        max_retries: int = 2,
    ):
        if not api_key:
            raise ValueError("api_key is required for ArticleEntityExtractor")
        self._client = openai.OpenAI(api_key=api_key, timeout=timeout)
        self.model = model
        self.max_retries = max_retries

    def extract(self, article_text: str, max_entities: int = 15) -> List[ExtractedEntity]:
        prompt = build_entity_prompt(article_text, max_entities)
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content or ""
                return self._parse(content, max_entities)
            except (RateLimitError, APITimeoutError) as exc:
                if attempt >= self.max_retries:
                    logger.error("Entity extraction failed after retries: %s", exc)
                    raise
                wait = 2 ** attempt
                logger.warning("Entity extraction transient error: %s (retry in %ss)", exc, wait)
                time.sleep(wait)
            except OpenAIError as exc:
                logger.error("Entity extraction OpenAI error: %s", exc)
                raise
        return []

    @staticmethod
    def _parse(content: str, max_entities: int) -> List[ExtractedEntity]:
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("Entity extractor produced non-JSON output: %s", exc)
            return []

        raw = data.get("entities", []) if isinstance(data, dict) else []
        if not isinstance(raw, list):
            return []

        entities: List[ExtractedEntity] = []
        for item in raw[:max_entities]:
            if not isinstance(item, dict):
                continue
            entity_type = (item.get("entity_type") or item.get("type") or "").lower()
            if entity_type not in _ALLOWED_TYPES:
                continue
            mention = (item.get("mention_text") or "").strip()
            if not mention:
                continue

            team_abbr = item.get("team_abbr")
            if isinstance(team_abbr, list) and team_abbr:
                team_abbr = team_abbr[0]
            team_name = item.get("team_name")
            if isinstance(team_name, list) and team_name:
                team_name = team_name[0]

            entities.append(
                ExtractedEntity(
                    entity_type=entity_type,
                    mention_text=mention,
                    confidence=_safe_float(item.get("confidence")),
                    rank=_safe_int(item.get("rank")),
                    position=item.get("position") if entity_type == "player" else None,
                    team_abbr=team_abbr if entity_type in ("player", "staff") else None,
                    team_name=team_name if entity_type in ("player", "staff") else None,
                )
            )

        entities.sort(key=lambda e: e.rank if e.rank is not None else 999)
        return entities


def _safe_float(value) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_int(value) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
