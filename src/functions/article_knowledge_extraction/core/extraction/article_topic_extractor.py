"""Article-level topic extraction via OpenAI (real-time, no Batch API)."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import List, Optional

import openai
from openai import APITimeoutError, OpenAIError, RateLimitError

from ..prompts import build_topic_prompt

logger = logging.getLogger(__name__)


@dataclass
class ExtractedTopic:
    topic: str
    confidence: Optional[float]
    rank: Optional[int]


class ArticleTopicExtractor:
    """Calls the LLM once to extract the most central topics of an article."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5.4-mini",
        timeout: int = 60,
        max_retries: int = 2,
    ):
        if not api_key:
            raise ValueError("api_key is required for ArticleTopicExtractor")
        self._client = openai.OpenAI(api_key=api_key, timeout=timeout)
        self.model = model
        self.max_retries = max_retries

    def extract(self, article_text: str, max_topics: int = 5) -> List[ExtractedTopic]:
        prompt = build_topic_prompt(article_text, max_topics)
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content or ""
                return self._parse(content, max_topics)
            except (RateLimitError, APITimeoutError) as exc:
                if attempt >= self.max_retries:
                    logger.error("Topic extraction failed after retries: %s", exc)
                    raise
                wait = 2 ** attempt
                logger.warning("Topic extraction transient error: %s (retry in %ss)", exc, wait)
                time.sleep(wait)
            except OpenAIError as exc:
                logger.error("Topic extraction OpenAI error: %s", exc)
                raise
        return []

    @staticmethod
    def _parse(content: str, max_topics: int) -> List[ExtractedTopic]:
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("Topic extractor produced non-JSON output: %s", exc)
            return []

        raw = data.get("topics", []) if isinstance(data, dict) else []
        if not isinstance(raw, list):
            return []

        topics: List[ExtractedTopic] = []
        for item in raw[:max_topics]:
            if not isinstance(item, dict):
                continue
            topic = item.get("topic")
            if not topic:
                continue
            topics.append(
                ExtractedTopic(
                    topic=str(topic),
                    confidence=_safe_float(item.get("confidence")),
                    rank=_safe_int(item.get("rank")),
                )
            )

        topics.sort(key=lambda t: t.rank if t.rank is not None else 999)
        return topics


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
