"""Prompt templates and builders for image selection LLM queries."""

from __future__ import annotations

from typing import Optional

# Words that strongly correlate with overlaid text, broadcast bugs, or thumbnails.
EXCLUSION_SUFFIX = "-logo -watermark -thumbnail -screenshot -graphic -poster -meme -overlay -lower-third"

IMAGE_QUERY_SYSTEM_PROMPT = (
    "You produce short web image search queries. "
    "Return only the query string, with no quotes, code fences, or extra text."
)

IMAGE_QUERY_PROMPT_TEMPLATE = (
    "Turn the article text into a concise image search query (max {max_words} words). "
    "Prioritize specific nouns (teams, players, coaches, venues) and time/context cues in the text. "
    "Avoid generic terms and avoid including site names or brands. "
    "Do NOT add keywords about graphics or thumbnails. "
    "Return only the query string.\n\n"
    "Article text:\n{article_text}\n"
)


def build_image_query(core_query: str) -> str:
    """Append exclusion terms to a core search query to filter unwanted image types."""
    core_query = " ".join(core_query.split())  # normalize spaces
    if not core_query:
        return EXCLUSION_SUFFIX.lstrip()
    return f"{core_query} {EXCLUSION_SUFFIX}"


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
