"""Prompt templates for article translation."""

from __future__ import annotations
from textwrap import dedent
from .contracts.translated_article import TranslationOptions, TranslationRequest

TRANSLATION_SYSTEM_PROMPT_TEMPLATE = (
    "You are a professional translator specializing in NFL coverage. "
    "Translate faithfully and idiomatically, preserving meaning and statistics. "
    "Honor domain terminology and proper nouns. "
    "Follow these tonal/style preferences: {tone_guidance}."
)

TRANSLATION_INSTRUCTIONS_TEMPLATE = dedent(
    """
    Translate the following NFL article from {source_language} to {target_language}.
    {tone_guidance}
    {structure_guidance}

    Terminology and fidelity:
    - Keep statistics, scores, player names, team/franchise names, league names, and acronyms EXACTLY as written.
    - Do not add, remove, or alter facts; do not summarize or editorialize.
    - Translate idioms and fixed expressions meaningfully (not literally) while preserving intent.
    - Maintain paragraph boundaries {paragraph_rule}.
    {preserve_clause}

    Localization (if applicable):
    {localization_clause}

    Output requirements:
    - Return ONLY raw JSON (no code fences, no Markdown, no extra text).
    - Keys: headline, sub_header, introduction_paragraph, content (array of strings).
    - Ensure valid JSON (properly escaped quotes/newlines).
    - Do not include null/empty strings unless the source is empty.

    JSON schema (informative, not to be echoed):
    {{
        "headline": string,
        "sub_header": string,
        "introduction_paragraph": string,
        "content": [ string, ... ]   // one element per paragraph in the translated body
    }}
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
        items = "\n".join(f"- Preserve the exact term '{t}' without translation." for t in request.preserve_terms)
        return items
    # Default guardrails even without a list
    return (
        "- Preserve EXACT casing and spelling for: team names, player names, league names (e.g., NFL), "
        "competition names (e.g., AFC, NFC), and acronyms."
    )

def _build_localization_clause(options: TranslationOptions) -> str:
    # Examples: "de-DE" uses „…“ quotes, decimal comma, DD.MM.YYYY dates, 24h times
    loc = (getattr(options, "locale", "") or "").strip()
    if loc.lower() in {"de-de", "de"}:
        return (
            "- Use German punctuation and typography: „…“ for quotations where appropriate.\n"
            "- Use decimal comma for numbers (e.g., 4,7) but preserve stats as printed if part of official notation.\n"
            "- Format dates as DD.MM.YYYY when natural to the sentence (do not alter within official titles or stats lines).\n"
            "- Use 24-hour time if time expressions occur."
        )
    if loc:
        return f"- Use punctuation and date/number conventions appropriate for locale '{loc}'."
    return "- Keep source punctuation/number/date conventions unless they read unnaturally in the target language."

def _build_paragraph_rule(options: TranslationOptions) -> str:
    keep = getattr(options, "keep_paragraphs", True)
    return "1:1 with the source" if keep else "unless a minor merge/split improves readability (keep content complete)"

def build_translation_prompt(
    request: TranslationRequest,
    options: TranslationOptions,
) -> str:
    """Create structured translation instructions for GPT."""
    paragraphs = "\n".join(
        f"Paragraph {i + 1}: {p}" for i, p in enumerate(request.content)
    )

    instructions = TRANSLATION_INSTRUCTIONS_TEMPLATE.format(
        source_language=request.source_language.upper(),
        target_language=request.language.upper(),
        tone_guidance=options.tone_guidance or "",
        structure_guidance=options.structure_guidance or "",
        preserve_clause=_build_preserve_clause(request),
        localization_clause=_build_localization_clause(options),
        paragraph_rule=_build_paragraph_rule(options),
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
        tone_guidance=(options.tone_guidance or "").lower(),
    )
