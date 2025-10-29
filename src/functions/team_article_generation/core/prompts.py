"""Prompt templates for team article generation."""

from __future__ import annotations

from textwrap import dedent

from .contracts.team_article import GenerationOptions, SummaryBundle

TEAM_ARTICLE_SYSTEM_PROMPT_TEMPLATE = (
    "You are a seasoned NFL beat writer creating a professional daily update for the {team_label}. "
    "Write from the perspective of the {team_label}, addressing readers who already follow the team closely. "
    "Focus on one main topic from the provided summaries—use other topics only as background context. "
    "Avoid coverage related to betting odds, fantasy projections, or game recaps/reviews. "
    "Do not speculate or invent details. Maintain a factual, cohesive, AP-style tone."
)

_team_article_instructions = dedent(
    """
    Using only the provided summaries, write a cohesive daily update article about the {team_label}.

    - Select **one** main storyline from the summaries and center the article around it.
    - Use other topics **only** as supporting context when relevant.
    - **Avoid**: betting/gambling angles, fantasy projections, and full game recaps/reviews.
    - Write naturally from the team’s perspective—assume readers are already in the team context.
    - Avoid repetitive constructions like “The {team_label} did…” unless needed for clarity.
    - Target a **2–4 minute read**, structured into clear, connected paragraphs (no fixed count).
    - Maintain an **objective, AP-style** tone—factual, concise, and free of speculation or rumor.
    - Do not invent statistics, quotes, injuries, or details not found in the summaries.
    - Ensure smooth narrative flow and avoid repetition.
    - **Return only raw JSON** (no code fences, no markdown, no extra text).

    Respond strictly with valid JSON using this schema:
    {{
        "headline": string,
        "sub_header": string,
        "introduction_paragraph": string,
        "content": [
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
