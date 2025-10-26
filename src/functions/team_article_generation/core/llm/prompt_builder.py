"""Prompt builder for GPT-5 article generation."""

from __future__ import annotations

from textwrap import dedent

from ..contracts.team_article import GenerationOptions, SummaryBundle


def build_prompt(bundle: SummaryBundle, options: GenerationOptions) -> str:
    """Create the GPT-5 prompt from summary inputs."""

    team_label = bundle.team_name or bundle.team_abbr
    summaries_block = "\n\n".join(f"Summary {index + 1}: {summary}" for index, summary in enumerate(bundle.summaries))
    prompt = f"Team: {team_label}\nAbbreviation: {bundle.team_abbr}\n\nSummaries:\n{summaries_block}"
    instructions = dedent(
        f"""
        Write a cohesive daily update article about the {team_label} using only the provided summaries.
        - {options.narrative_focus}
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
    return f"{instructions}\n\n{prompt}"
