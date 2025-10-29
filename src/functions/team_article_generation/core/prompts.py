"""Prompt templates for team article generation."""

from __future__ import annotations

from textwrap import dedent

from ..contracts.team_article import GenerationOptions, SummaryBundle

TEAM_ARTICLE_SYSTEM_PROMPT_TEMPLATE = (
    "You are an experienced NFL beat writer crafting a daily update article. "
    "Use only the provided summaries, avoid speculation, and ensure the piece reads like a cohesive story. "
    "Write in third person about the {team_label}."
)

TEAM_ARTICLE_INSTRUCTIONS_TEMPLATE = dedent(
    """
    Write a cohesive daily update article about the {team_label} using only the provided summaries.
    - {narrative_focus}
    - Craft a compelling headline and a succinct sub-header.
    - Begin with a short introduction paragraph summarizing the main storyline.
    - Provide 3-4 subsequent paragraphs that expand on key points, quotes, and context.
    - Do not invent statistics, quotes, injuries, or rumors not found in the summaries.
    - Maintain objective tone and AP-style writing.
    - Avoid repeating the same information across sections.
    - Output must be factual and concise.
            - Respond strictly with valid JSON using the schema:
                {{
                    "headline": string,
                    "sub_header": string,
                    "introduction_paragraph": string,
                    "content": [string, string, string, string?]
                }}
    """
).strip()

PROMPT_CONTEXT_TEMPLATE = (
    "Team: {team_label}\nAbbreviation: {team_abbr}\n\nSummaries:\n{summaries}"
)


def build_team_article_prompt(
    bundle: SummaryBundle,
    options: GenerationOptions,
) -> str:
    """Create the GPT prompt that drives article generation."""

    team_label = bundle.team_name or bundle.team_abbr
    summaries_block = "\n\n".join(
        f"Summary {index + 1}: {summary}" for index, summary in enumerate(bundle.summaries)
    )
    instructions = TEAM_ARTICLE_INSTRUCTIONS_TEMPLATE.format(
        team_label=team_label,
        narrative_focus=options.narrative_focus,
    )
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
