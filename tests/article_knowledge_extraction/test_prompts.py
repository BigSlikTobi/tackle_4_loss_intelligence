"""Prompt integrity tests — article-level prompts must stay schema-aligned
with the fact-level prompts so downstream grouping sees a uniform topic
vocabulary."""

from __future__ import annotations

import re

from src.functions.article_knowledge_extraction.core.prompts import (
    build_entity_prompt,
    build_topic_prompt,
)
from src.functions.knowledge_extraction.core.prompts import (
    TOPIC_EXTRACTION_PROMPT_TEMPLATE,
)


_FACTS_CATEGORY_RE = re.compile(r"^- (.+)$", re.MULTILINE)


def _extract_facts_categories() -> set[str]:
    return set(_FACTS_CATEGORY_RE.findall(TOPIC_EXTRACTION_PROMPT_TEMPLATE))


def test_article_topic_categories_cover_facts_topic_categories():
    """Every fact-level category must appear verbatim in the article prompt.
    Downstream grouping relies on a uniform vocabulary across both paths."""
    article_prompt = build_topic_prompt("irrelevant body", max_items=5)
    missing = [c for c in _extract_facts_categories() if c not in article_prompt]
    assert not missing, (
        "Article-level prompt is missing categories that exist in the fact-level "
        f"prompt: {missing}"
    )


def test_topic_prompt_includes_article_body_and_max_items():
    prompt = build_topic_prompt("ARTICLE_BODY_SENTINEL", max_items=4)
    assert "ARTICLE_BODY_SENTINEL" in prompt
    assert "at most 4" in prompt or "most 4 topics" in prompt


def test_entity_prompt_includes_article_body_and_max_items():
    prompt = build_entity_prompt("ARTICLE_BODY_SENTINEL", max_items=7)
    assert "ARTICLE_BODY_SENTINEL" in prompt
    assert "at most 7 entities" in prompt
