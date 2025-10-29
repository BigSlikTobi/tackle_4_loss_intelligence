"""Prompt templates for team article generation."""

from __future__ import annotations

from textwrap import dedent

from .contracts.team_article import GenerationOptions, SummaryBundle

TEAM_ARTICLE_SYSTEM_PROMPT_TEMPLATE = (
    "You are a seasoned NFL beat writer crafting a professional, timely daily update for the {team_label}. "
    "Your goal is to inform loyal {team_label} followers about a specific, recent development that directly concerns the team. "
    "Write from inside the team’s perspective — as if reporting from the facility or press conference. "
    "Focus on one concrete, newsworthy event or storyline from the provided summaries — "
    "such as roster changes, press statements, injuries, trades, strategy updates, or performance reactions. "
    "Ignore or downplay unrelated league context. "
    "Avoid betting odds, fantasy projections, or general season outlooks. "
    "Do not speculate or invent information. Maintain a factual, cohesive, AP-style tone with a sense of immediacy."
)

_team_article_instructions = dedent(
    """
    Using only the provided summaries, write a cohesive and timely daily update article about the {team_label}.

    **Goal**
    - Deliver a clear, *on-point* article about what *recently happened* to or around the team.
    - Identify one *specific event or storyline* that is recent, concrete, and directly team-related.
    - Avoid writing broad reflections, previews, or long-term analyses unless they are part of today’s event.

    **Guidelines**
    - Focus strictly on the {team_label} — not league-wide developments.
    - Use other topics only as brief context if they support the main story.
    - Keep the article grounded in the *present moment* (e.g., “today,” “this week,” “following Sunday’s loss,” etc.).
    - Highlight tangible developments: roster changes, coach comments, player reactions, new injuries, or front-office actions.
    - Do not include speculation, betting/gambling angles, fantasy talk, or game recaps/reviews.
    - Write in a natural, professional tone consistent with AP-style reporting.
    - Keep it concise and factual — no fluff or generic statements.
    - Target a **2–4 minute read**, structured in connected paragraphs with a clear narrative flow.
    - **Return only raw JSON** (no markdown, no explanations).

    **Output format (strict JSON):**
    {{
        "headline": string,                  // Specific, timely, no clickbait
        "sub_header": string,                // Expands on the main news angle
        "introduction_paragraph": string,    // Sets up the immediate story and its relevance
        "content": [                         // 3–6 paragraphs expanding on details, quotes, reactions, or context
            string,
            string,
            string,
            string?,
            string?,
            string?
        ]
    }}
    """
).strip()


TEAM_ARTICLE_INSTRUCTIONS_TEMPLATE = _team_article_instructions

PROMPT_CONTEXT_TEMPLATE = (
    "Team: {team_label}\nAbbreviation: {team_abbr}\n\nSummaries:\n{summaries}"
)

def build_team_article_prompt(bundle: SummaryBundle, options: GenerationOptions) -> str:
    """Create the GPT prompt that drives article generation."""
    team_label = bundle.team_name or bundle.team_abbr
    summaries_block = "\n\n".join(
        f"Summary {i+1}: {s}" for i, s in enumerate(bundle.summaries)
    )

    # Base instructions
    instructions = TEAM_ARTICLE_INSTRUCTIONS_TEMPLATE.format(team_label=team_label)

    # Conditionally surface narrative_focus, if provided
    if getattr(options, "narrative_focus", None):
        instructions += f"\n\nAdditional focus guidance: {options.narrative_focus}"

    prompt_context = PROMPT_CONTEXT_TEMPLATE.format(
        team_label=team_label,
        team_abbr=bundle.team_abbr,
        summaries=summaries_block,
    )
    return f"{instructions}\n\n{prompt_context}"

def build_team_article_system_prompt(bundle: SummaryBundle) -> str:
    """Create the system-level instructions for the LLM."""
    team_label = bundle.team_name or bundle.team_abbr
    return TEAM_ARTICLE_SYSTEM_PROMPT_TEMPLATE.format(team_label=team_label)
