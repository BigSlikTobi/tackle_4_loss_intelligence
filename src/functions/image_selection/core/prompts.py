"""Prompt templates and builders for image selection LLM queries."""

from __future__ import annotations

from typing import Optional

IMAGE_QUERY_PROMPT_TEMPLATE = (
    "You turn article text into a concise web image search query. "
    "Return only the final query with at most {max_words} words, "
    "favoring specific nouns (teams, players, locations) and avoiding generic words.\n\n"
    "Article text:\n{article_text}\n"
)

IMAGE_QUERY_SYSTEM_PROMPT = (
    "You produce short web image search queries. Return only the query string."
)


def build_image_query_prompt(
    article_text: str,
    *,
    max_words: int,
    template: Optional[str] = None,
) -> str:
    """Format the article text using the provided or default image query template."""

    normalized_template = template or IMAGE_QUERY_PROMPT_TEMPLATE
    truncated_text = article_text[:2000]
    return normalized_template.format(
        article_text=truncated_text,
        max_words=max_words,
    )
