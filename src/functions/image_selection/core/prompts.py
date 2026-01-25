"""Prompt templates and builders for image selection LLM queries."""

from __future__ import annotations

from typing import Optional

# Words that strongly correlate with overlaid text, broadcast bugs, or thumbnails.
EXCLUSION_SUFFIX = "-logo -watermark -thumbnail -screenshot -graphic -poster -meme -overlay -lower-third -infographic -chart -stats"

IMAGE_QUERY_SYSTEM_PROMPT = (
    "You are an expert at crafting precise image search queries for NFL football content. "
    "Your goal is to generate a query that will find a high-quality action photo or portrait "
    "that directly illustrates the main subject of the article. "
    "Return ONLY the search query string - no quotes, no explanations, no formatting."
)

IMAGE_QUERY_PROMPT_TEMPLATE = (
    "Create a precise image search query (max {max_words} words) for the article below.\n\n"
    "RULES:\n"
    "1. IDENTIFY the primary subject: a specific player, coach, team matchup, or event.\n"
    "2. USE FULL NAMES (e.g., 'Patrick Mahomes' not 'Mahomes', 'Kansas City Chiefs' not 'Chiefs').\n"
    "3. ADD CONTEXT: Include the sport 'NFL' and action descriptors like 'game action', "
    "'press conference', 'touchdown', 'celebration', or 'sideline'.\n"
    "4. For TEAM stories without a specific player, use format: '[Team full name] NFL [context]'.\n"
    "5. For PLAYER stories, use format: '[Player full name] NFL [action/context]'.\n"
    "6. AVOID: generic words like 'football', 'sports', 'news', team nicknames alone, "
    "abbreviations, or years unless essential.\n\n"
    "EXAMPLES:\n"
    "- Article about Mahomes injury → 'Patrick Mahomes Kansas City Chiefs injury sideline'\n"
    "- Article about Bills vs Dolphins game → 'Buffalo Bills Miami Dolphins NFL game action'\n"
    "- Article about coaching hire → 'Mike Vrabel New England Patriots head coach press conference'\n\n"
    "Article text:\n{article_text}\n\n"
    "Search query:"
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
