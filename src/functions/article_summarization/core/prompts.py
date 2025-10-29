"""Prompt helpers for article summarization LLM requests."""

from __future__ import annotations

from ..contracts.summary import SummarizationOptions, SummarizationRequest

SUMMARIZATION_PROMPT_TEMPLATE = (
    "You are an NFL beat reporter summarizing a news article for internal editors. "
    "Remove boilerplate, advertisements, video transcripts, promotional copy, and unrelated paragraphs. "
    "{team_clause} "
    "Preserve key facts, quotes, and meaningful context without speculation. "
    "Do not add analysis or commentary. Output a concise paragraph (120-180 words). "
    "Never include phrases related to: {removal_clause}.\n\n"
    "Article Content:\n"
    "{article_content}"
)


def build_summarization_prompt(
    request: SummarizationRequest,
    options: SummarizationOptions,
) -> str:
    """Construct the prompt used for Gemini summarization."""

    team_clause = (
        f"Focus on insights about the {request.team_name}."
        if request.team_name
        else "Focus only on the team mentioned in the article."
    )
    removal_clause = ", ".join(options.remove_patterns)
    return SUMMARIZATION_PROMPT_TEMPLATE.format(
        team_clause=team_clause,
        removal_clause=removal_clause,
        article_content=request.content,
    )
