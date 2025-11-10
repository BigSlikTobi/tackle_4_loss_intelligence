"""Prompt templates for team article generation."""

from __future__ import annotations

from textwrap import dedent

from .contracts.team_article import GenerationOptions, SummaryBundle

TEAM_ARTICLE_SYSTEM_PROMPT_TEMPLATE = (
    "You are a seasoned NFL beat reporter writing from inside the {team_label} organization. "
    "Your job is to create a focused, engaging, and professional daily update that explains a specific, "
    "recent development affecting the team. Write as if reporting from the facility, locker room, or press availability. "
    "Your tone should be informed, confident, narrative, and detailed — not generic. "
    "Do not speculate or invent details. Do not include betting angles or fantasy advice. "
    "Ignore unrelated league context. Your article should feel timely, grounded, and clearly connected to one real event."
)

_team_article_instructions = dedent(
    """
    **Task Overview**
    The provided summaries may contain multiple pieces of information. Your first responsibility is to:
    1) Identify *one* storyline that is:
       - About the {team_label},
       - Recent, concrete, and newsworthy,
       - Clearly supported by the summaries.

    Focus the entire article on this one storyline. Do not merge multiple unrelated stories.

    **Automatic Style Selection (No Manual Parameter Needed)**

    After selecting the main storyline, assign STYLE based on the storyline type:

    - If the storyline involves:
        • Injury status updates
        • Return-to-play progress
        • Rehab timelines
      → STYLE = "Emotional"  
        Use a grounded, human-centered tone. Acknowledge player experience, coach sentiment, or team mood.

    - If the storyline involves:
        • Trades
        • Signings / releases / waivers
        • Depth chart changes
        • Rotational role adjustments
      → STYLE = "Analytical"  
        Emphasize reasoning, fit, role implications, and strategic context.

    - If the storyline involves:
        • Sudden or unexpected developments
        • Emergency roster actions
        • Immediate-impact announcements
      → STYLE = "Urgent"  
        Use tighter pacing, short lead-in sentences, and a clear “this just happened” feel.

    - Otherwise:
      → STYLE = "Standard"  
        Use a balanced, professional beat-report tone.

    STYLE affects tone and pacing — not facts or article structure.

    **Writing Style Requirements**
    - Write in connected paragraphs with natural transitions.
    - Set the scene where appropriate (facility, press comments, timing reference).
    - Do not exaggerate or dramatize beyond what is supported.
    - Maintain factual clarity and direct relevance.
    - Keep the article grounded in the present moment.

    **Length & Structure**
    Target a 2–4 minute read. Expand meaningfully, not through filler.

    Recommended structure:
    1. Introduction: what happened + why it matters today.
    2. Development and details: explain the situation clearly.
    3. Implications / context directly relevant to the event.
    4. Conclude with the current status, next steps, or anticipation.

    **Output Format (Strict JSON Only — No Markdown):**
    {
        "headline": string,                  // Clear and timely
        "sub_header": string,                // One-sentence expansion of angle
        "introduction_paragraph": string,    // Strong lead framing the story
        "content": [
            string,
            string,
            string,
            string?,
            string?,
            string?
        ]
    }
    """
).strip()


TEAM_ARTICLE_INSTRUCTIONS_TEMPLATE = _team_article_instructions

PROMPT_CONTEXT_TEMPLATE = (
    "Team: {team_label}\nAbbreviation: {team_abbr}\n\nSummaries:\n{summaries}"
)

def build_team_article_prompt(bundle: SummaryBundle, options: GenerationOptions) -> str:
    """Create the GPT prompt that drives article generation."""
    team_label = bundle.team_name or bundle.team_abbr
    summaries = [summary.strip() for summary in bundle.summaries if summary and summary.strip()]
    if not summaries:
        msg = "Cannot build team article prompt without at least one source summary"
        raise ValueError(msg)

    summaries_block = "\n\n".join(
        f"Summary {i + 1}: {summary}" for i, summary in enumerate(summaries)
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
