"""Prompt helpers for article summarization LLM requests."""

from __future__ import annotations

from .contracts.summary import SummarizationOptions, SummarizationRequest

SUMMARIZATION_PROMPT_TEMPLATE = (
    "Summarize the article below into a clean, factual digest for downstream automation.\n"
    "Guidelines:\n"
    "1. Use only information explicitly present in the article. Do not speculate or add outside context.\n"
    "2. Preserve chronology, quoted language, and transaction direction exactly as written. "
    "When trades or acquisitions are described, state who acquires whom and what is exchanged without reversing parties.\n"
    "3. Strip advertisements, navigation copy, social media prompts, and unrelated sidebars.\n"
    "4. Keep the tone neutral and reportorial; do not add opinion or hype.\n"
    "5. Produce a single cohesive paragraph.\n"
    "{team_clause}\n"
    "Avoid including phrases related to: {removal_clause}.\n\n"
    "Article Content:\n"
    "{article_content}"
)


def build_summarization_prompt(
    request: SummarizationRequest,
    options: SummarizationOptions,
) -> str:
    """Construct the prompt used for Gemini summarization."""

    team_clause = ""
    if request.team_name:
        team_clause = (
            f"\n7. When referencing the {request.team_name}, mirror the article's wording precisely "
            "and do not infer motivations or extra context."
        )
    removal_clause = ", ".join(options.remove_patterns)
    # Escape braces in article content to prevent .format() from treating them as placeholders
    escaped_content = request.content.replace("{", "{{").replace("}", "}}")
    return SUMMARIZATION_PROMPT_TEMPLATE.format(
        team_clause=team_clause,
        removal_clause=removal_clause,
        article_content=escaped_content,
    )
