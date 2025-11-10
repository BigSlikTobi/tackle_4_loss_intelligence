"""Prompt templates for article translation (publication-quality, rhythm-aware)."""

from __future__ import annotations
from textwrap import dedent
from .contracts.translated_article import TranslationOptions, TranslationRequest

# ---- Defaults to reduce literal, uninspired output --------------------------------

# A small anti-calque map the prompt can surface as guidance (not enforced code-side).
# These are frequent NFL-lingo traps that read poorly in German when translated literally.
_DEFAULT_ANTI_CALQUES = [
    ("elevation (roster context)", "hochgezogen / hochgestuft ins Active Roster (nicht: Erhöhung)"),
    ("depth option", "Backup-Option / Kaderbreite"),
    ("pipeline (team ops)", "Ablauf / Kette / interner Prozess (nicht: Pipeline)"),
    ("facility", "Teamgelände / Trainingszentrum, je nach Kontext"),
    ("statement (PR/coach)", "Aussage / Statement (wenn offiziell PR: 'Mitteilung')"),
    ("ahead of (game/week)", "vor / mit Blick auf / im Vorfeld"),
    ("standout", "herausragend / auffällig"),
    ("reps (practice)", "SNAPS/Übungseinheiten / Wiederholungen (je nach Kontext)"),
    ("waived", "entlassen / auf die Waiver-Liste gesetzt (kontextabhängig)"),
    ("activated", "aktiviert / ins Active Roster berufen"),
    ("designated to return", "für eine Rückkehr designiert"),
]

# A style preset for German sports journalism; appended automatically for de-DE.
_DE_SPORTS_DESK_PRESET = dedent(
    """
    Stilvorgaben (deutscher Sportjournalismus):
    - Natürlich, publikationsreif, lebendig ohne Effekthascherei.
    - Vermeide falsche Freunde und unnötige Anglizismen.
    - Variiere Satzlängen für einen flüssigen Leserythmus; übernimm Tempo und Akzente des Originals, nicht die wörtliche Struktur.
    - Verwende klare Verben, reduziere Nominalstil, setze Attribute sparsam.
    """
).strip()

# ---- System prompt ----------------------------------------------------------------

TRANSLATION_SYSTEM_PROMPT_TEMPLATE = (
    "You are a professional translator specializing in NFL coverage for publication. "
    "Your task is to deliver faithful, idiomatic, publication-quality German that preserves facts, figures, and intent. "
    "Translate for humans, not word-by-word. Mirror the source text's rhythm and emphasis without copying its syntax. "
    "Honor domain terminology and proper nouns. "
    "Follow these tonal/style preferences: {tone_guidance} "
    "{style_preset}"
)

# ---- Instruction prompt ------------------------------------------------------------

TRANSLATION_INSTRUCTIONS_TEMPLATE = dedent(
    """
    Translate the following NFL article from {source_language} to {target_language}.
    {tone_guidance}
    {structure_guidance}

    Workflow (apply in sequence):
    1) Faithful pass: Capture meaning, facts, and nuance precisely—no omissions, no additions.
    2) Fluency pass: Rewrite into natural {target_language_label} sports-desk prose. Mirror rhythm/energy (Tempo, Satzlängen, Schwerpunkt),
       avoid calques, prefer starke Verben, reduziere Nominalstil.
    3) Final checks: Terminology, locale, typography, JSON validity.

    Terminology and fidelity:
    - Keep statistics, scores, player names, team/franchise names, league names, and acronyms EXACTLY as written.
    - Do not add, remove, or alter facts; do not summarize or editorialize.
    - Translate idioms and fixed expressions meaningfully (not literally) while preserving intent.
    - Maintain paragraph boundaries {paragraph_rule}.
    {preserve_clause}

    Anti-calque guardrails (examples, not exhaustive):
    {anti_calques}

    Localization (if applicable):
    {localization_clause}

    Output requirements:
    - Return ONLY raw JSON (no code fences, no Markdown, no extra text).
    - Keys: headline, sub_header, introduction_paragraph, content (array of strings).
    - Ensure valid JSON (properly escaped quotes/newlines).
    - Do not include null/empty strings unless the source is empty.
    - If the source uses a term with a well-known German footballing equivalent, use the idiomatic German (see anti-calque list).

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

# ---- Helpers to assemble dynamic clauses -------------------------------------------

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
            "- Use decimal comma for numbers (e.g., 4,7) but preserve stats exactly if part of official notation.\n"
            "- Format dates as DD.MM.YYYY when natural to the sentence (do not alter within official titles or stats lines).\n"
            "- Use 24-hour time if time expressions occur."
        )
    if loc:
        return f"- Use punctuation and date/number conventions appropriate for locale '{loc}'."
    return "- Keep source punctuation/number/date conventions unless they read unnaturally in the target language."

def _build_paragraph_rule(options: TranslationOptions) -> str:
    keep = getattr(options, "keep_paragraphs", True)
    return "1:1 with the source" if keep else "unless a minor merge/split improves readability (keep content complete)"

def _build_anti_calques(options: TranslationOptions) -> str:
    """
    Build a short bullet list that reminds the model of common NFL calques to avoid.
    Users can extend via options.glossary (preferred equivalents) if provided.
    """
    custom_glossary = getattr(options, "glossary", None) or {}
    bullets = []

    # Include defaults first
    for src, tgt in _DEFAULT_ANTI_CALQUES:
        bullets.append(f"- {src} → {tgt}")

    # Then include user-provided strong preferences
    # Expecting a dict like {"elevation": "hochgezogen ins Active Roster"}
    if isinstance(custom_glossary, dict) and custom_glossary:
        for src, tgt in custom_glossary.items():
            bullets.append(f"- {src} → {tgt}")

    return "\n".join(bullets)

def _build_style_preset(options: TranslationOptions) -> str:
    """
    If locale is German, append a compact preset for German sports-desk style.
    Also allow an explicit mirror_rhythm flag to emphasize cadence preservation.
    """
    loc = (getattr(options, "locale", "") or "").strip().lower()
    mirror = getattr(options, "mirror_rhythm", True)  # default on
    preset_parts = []

    if loc in {"de-de", "de"}:
        preset_parts.append(_DE_SPORTS_DESK_PRESET)

    if mirror:
        preset_parts.append(
            "Be deliberate about rhythm: vary sentence length, carry momentum across clauses, "
            + "and let punchy details land at sentence ends. Do NOT mechanically mirror syntax."
        )

    extra_tone = getattr(options, "tone_guidance", "")
    if extra_tone:
        preset_parts.append(str(extra_tone))

    return (" " + " ".join(preset_parts)).strip() if preset_parts else ""

# ---- Public builders (backward compatible names) -----------------------------------

def build_translation_prompt(
    request: TranslationRequest,
    options: TranslationOptions,
) -> str:
    """Create structured translation instructions for GPT (rhythm-aware, anti-calque)."""
    paragraphs = "\n".join(
        f"Paragraph {i + 1}: {p}" for i, p in enumerate(request.content)
    )

    anti_calques = _build_anti_calques(options)

    # Human-readable language label (e.g., "German") for one line in the prompt
    target_lang_label = getattr(options, "language_label", "") or options.language if hasattr(options, "language") else "the target language"

    instructions = TRANSLATION_INSTRUCTIONS_TEMPLATE.format(
        source_language=getattr(request, "source_language", "EN").upper(),
        target_language=getattr(options, "language", getattr(request, "language", "DE")).upper(),
        target_language_label=target_lang_label,
        tone_guidance=options.tone_guidance or "",
        structure_guidance=options.structure_guidance or "",
        preserve_clause=_build_preserve_clause(request),
        localization_clause=_build_localization_clause(options),
        paragraph_rule=_build_paragraph_rule(options),
        anti_calques=anti_calques,
    )

    article_context = ARTICLE_CONTEXT_TEMPLATE.format(
        headline=request.headline,
        sub_header=request.sub_header,
        introduction=request.introduction_paragraph,
        body=paragraphs,
    )

    return f"{instructions}\n\n{article_context}"

def build_translation_system_prompt(options: TranslationOptions) -> str:
    """Create the system instructions used for translation (adds style preset + rhythm)."""
    style_preset = _build_style_preset(options)
    return TRANSLATION_SYSTEM_PROMPT_TEMPLATE.format(
        tone_guidance=(options.tone_guidance or "").strip(),
        style_preset=(" " + style_preset) if style_preset else "",
    )
