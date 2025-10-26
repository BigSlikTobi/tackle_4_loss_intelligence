"""Prompt construction utilities for translation."""

from __future__ import annotations

from textwrap import dedent

from ..contracts.translated_article import TranslationOptions, TranslationRequest


def build_prompt(request: TranslationRequest, options: TranslationOptions) -> str:
    """Create structured translation instructions for GPT."""

    preserve_clause = "".join(
        f"- Preserve the exact term '{term}' without translation.\n" for term in request.preserve_terms
    ) or "- Preserve team names, player names, and acronyms exactly as written.\n"

    paragraphs = "\n".join(
        f"Paragraph {index + 1}: {paragraph}" for index, paragraph in enumerate(request.content)
    )

    instructions = dedent(
        f"""
        Translate the following NFL article from {request.source_language.upper()} into {request.language.upper()}.
        {options.tone_guidance}
        {options.structure_guidance}
        - Keep statistics, player names, and competition data accurate.
        {preserve_clause.strip()}
        - Respond strictly as valid JSON with keys: headline, sub_header, introduction_paragraph, content (array of strings).
        """
    ).strip()

    article_context = dedent(
        f"""
        Headline: {request.headline}
        SubHeader: {request.sub_header}
        Introduction: {request.introduction_paragraph}
        Body:
        {paragraphs}
        """
    ).strip()

    return f"{instructions}\n\n{article_context}"
