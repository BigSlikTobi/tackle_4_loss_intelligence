"""Prompt builders for knowledge extraction LLM workflows."""

from __future__ import annotations

from textwrap import dedent

TOPIC_EXTRACTION_PROMPT_TEMPLATE = dedent(
    """
    Classify NFL topics from this text. Return ONLY categories from this list (exact names, lowercase):
    Quarterback Performance & Analysis, Running Back & Rushing Game, Wide Receiver & Passing Game, Defense & Turnovers, Coaching & Play Calling, Injuries & Player Health, Team Performance & Trends, Season Outlook & Predictions, Rookies & Emerging Players, Draft & College Prospects, Trades, Signings & Roster Moves, Contracts & Cap Management, Game Analysis & Highlights, Statistics & Rankings, Fantasy Football Impact, Offseason & Training Camp, Special Teams & Kicking Game, Refereeing & Rules, Player Profiles & Interviews, Team Culture & Leadership, League News & Administration, Off-Field & Lifestyle, Media & Fan Reactions

    Rules: max {max_items} topics, ranked by importance (1=primary, 2=secondary, 3+=minor), confidence 0-1.

    Return JSON: {{"topics":[{{"topic":"<category>","confidence":0.95,"rank":1}}]}}

    Text: {summary_text}
    """
).strip()

ENTITY_EXTRACTION_PROMPT_TEMPLATE = dedent(
    """
    Extract ALL NFL entities from this text. Entity types: team, player, game, staff.

    For each entity include: type, mention_text, confidence (0-1), rank (1=primary, 2=secondary, 3+=minor).
    - team: also include team_name (full), team_abbr (NFL abbr e.g. NYJ, KC, IND)
    - player: also include position (QB/RB/WR/TE/CB/DT/DE/LB/S/K/P), team_name, team_abbr. Infer position/team from context when available.
    - staff: also include role (e.g. "General Manager", "Head Coach"), team_name, team_abbr
    - game: also include teams array, context (week/round)

    Extract with partial info rather than skip. Prioritize completeness.

    Return up to {max_items} entities as JSON ordered by rank:
    {{"entities":[{{"type":"player","mention_text":"Sauce Gardner","position":"CB","team_name":"New York Jets","team_abbr":"NYJ","confidence":0.95,"rank":1}}]}}

    Text: {summary_text}
    """
).strip()

BATCHED_ENTITY_EXTRACTION_PROMPT_TEMPLATE = dedent(
    """
    Extract ALL NFL entities from each numbered fact below. Entity types: team, player, game, staff.

    For each entity include: type, mention_text, confidence (0-1), rank (1=primary, 2=secondary, 3+=minor).
    - team: also include team_name (full), team_abbr (NFL abbr e.g. NYJ, KC, IND)
    - player: also include position (QB/RB/WR/TE/CB/DT/DE/LB/S/K/P), team_name, team_abbr. Infer position/team from context when available.
    - staff: also include role, team_name, team_abbr
    - game: also include teams array, context (week/round)

    Extract with partial info rather than skip. Max {max_items} entities per fact.

    Return a JSON array with one object per fact, in order:
    [{{"fact_index":1,"entities":[{{"type":"player","mention_text":"Josh Allen","position":"QB","team_abbr":"BUF","confidence":0.95,"rank":1}}]}},{{"fact_index":2,"entities":[]}}]

    Facts:
    {numbered_facts}
    """
).strip()


def build_topic_extraction_prompt(summary_text: str, max_topics: int) -> str:
    """Format the topic extraction instructions."""

    return TOPIC_EXTRACTION_PROMPT_TEMPLATE.format(
        summary_text=summary_text,
        max_items=max_topics,
    )


def build_entity_extraction_prompt(summary_text: str, max_entities: int) -> str:
    """Format the entity extraction instructions."""

    return ENTITY_EXTRACTION_PROMPT_TEMPLATE.format(
        summary_text=summary_text,
        max_items=max_entities,
    )


def build_batched_entity_extraction_prompt(
    facts: list[str], max_entities_per_fact: int
) -> str:
    """Format the batched entity extraction prompt for multiple facts."""

    numbered_facts = "\n".join(
        f"{i+1}. {fact}" for i, fact in enumerate(facts)
    )
    return BATCHED_ENTITY_EXTRACTION_PROMPT_TEMPLATE.format(
        numbered_facts=numbered_facts,
        max_items=max_entities_per_fact,
    )
