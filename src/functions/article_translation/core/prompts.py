"""Prompt templates for article translation flows."""

from __future__ import annotations

from textwrap import dedent

from ..contracts.translated_article import TranslationOptions, TranslationRequest

TRANSLATION_SYSTEM_PROMPT_TEMPLATE = (
    "You are a professional translator specialising in NFL coverage. "
    "Ensure terminology stays accurate, preserve statistics, and keep the style consistent with {tone_guidance}."
)

TRANSLATION_INSTRUCTIONS_TEMPLATE = dedent(
    """
    Translate the following NFL article from {source_language} into {target_language}.
    {tone_guidance}
    {structure_guidance}
    - Keep statistics, player names, and competition data accurate.
    {preserve_clause}
    - Respond strictly as valid JSON with keys: headline, sub_header, introduction_paragraph, content (array of strings).
    """
).strip()

ARTICLE_CONTEXT_TEMPLATE = dedent(
    """
    Headline: {headline}
    SubHeader: {sub_header}
    Introduction: {introduction}
    Body:
    {body}
    """
).strip()


def _build_preserve_clause(request: TranslationRequest) -> str:
    if request.preserve_terms:
        return "\n".join(
            f"- Preserve the exact term '{term}' without translation." for term in request.preserve_terms
        )
    return "- Preserve team names, player names, and acronyms exactly as written."


def build_translation_prompt(
    request: TranslationRequest,
    options: TranslationOptions,
) -> str:
    """Create structured translation instructions for GPT."""

    paragraphs = "\n".join(
        f"Paragraph {index + 1}: {paragraph}" for index, paragraph in enumerate(request.content)
    )

    instructions = TRANSLATION_INSTRUCTIONS_TEMPLATE.format(
        source_language=request.source_language.upper(),
        target_language=request.language.upper(),
        tone_guidance=options.tone_guidance,
        structure_guidance=options.structure_guidance,
        preserve_clause=_build_preserve_clause(request),
    )

    article_context = ARTICLE_CONTEXT_TEMPLATE.format(
        headline=request.headline,
        sub_header=request.sub_header,
        introduction=request.introduction_paragraph,
        body=paragraphs,
    )

    return f"{instructions}\n\n{article_context}"


def build_translation_system_prompt(options: TranslationOptions) -> str:
    """Create the system instructions used for translation."""

    return TRANSLATION_SYSTEM_PROMPT_TEMPLATE.format(
        tone_guidance=options.tone_guidance.lower(),
    )
