"""Prompt builders tuned for full-article inputs.

The topic category list is copied verbatim from the fact-level
`knowledge_extraction` module so that grouping consumers see a uniform topic
vocabulary across both extraction paths.
"""

from __future__ import annotations

from textwrap import dedent


ARTICLE_TOPIC_EXTRACTION_PROMPT = dedent(
    """
    You are analyzing a full NFL article. Identify the {max_items} most central
    topics from the list below. Return ONLY categories from this list (exact names):

    - Quarterback Performance & Analysis
    - Running Back & Rushing Game
    - Wide Receiver & Passing Game
    - Defense & Turnovers
    - Coaching & Play Calling
    - Injuries & Player Health
    - Team Performance & Trends
    - Season Outlook & Predictions
    - Rookies & Emerging Players
    - Draft & College Prospects
    - Trades, Signings & Roster Moves
    - Contracts & Cap Management
    - Game Analysis & Highlights
    - Statistics & Rankings
    - Fantasy Football Impact
    - Offseason & Training Camp
    - Special Teams & Kicking Game
    - Refereeing & Rules
    - Player Profiles & Interviews
    - Team Culture & Leadership
    - League News & Administration
    - Off-Field & Lifestyle
    - Media & Fan Reactions

    Rules:
    - Choose topics central to the article's *main* thrust, not incidental mentions.
    - Rank by importance (1=primary, 2=secondary, 3+=minor). Confidence in [0,1].
    - Return at most {max_items} topics.

    Return JSON exactly in this shape:
    {{"topics":[{{"topic":"<category>","confidence":0.95,"rank":1}}]}}

    Article:
    {article_text}
    """
).strip()


ARTICLE_ENTITY_EXTRACTION_PROMPT = dedent(
    """
    Extract NFL entities from the full article below. Entity types: team, player,
    game, staff.

    For each entity include: type, mention_text, confidence (0-1), rank
    (1=article is primarily about them, 2=secondary focus, 3+=passing mention).
    - team: also include team_name (full) and team_abbr (e.g. NYJ, KC, IND).
    - player: also include position (QB/RB/WR/TE/CB/DT/DE/LB/S/K/P), team_name,
      team_abbr. Infer position/team from context when available.
    - staff: also include role (e.g. "General Manager", "Head Coach"),
      team_name, team_abbr.
    - game: also include teams (array of team names or abbreviations) and
      context (week/round if mentioned).

    Rules:
    - Deduplicate variations of the same entity to a single canonical mention.
    - Prioritize entities *central* to the article over passing mentions.
    - Return at most {max_items} entities, ordered by rank ascending.

    Return JSON exactly in this shape:
    {{"entities":[{{"type":"player","mention_text":"Sauce Gardner","position":"CB","team_name":"New York Jets","team_abbr":"NYJ","confidence":0.95,"rank":1}}]}}

    Article:
    {article_text}
    """
).strip()


def build_topic_prompt(article_text: str, max_items: int) -> str:
    return ARTICLE_TOPIC_EXTRACTION_PROMPT.format(
        article_text=article_text,
        max_items=max_items,
    )


def build_entity_prompt(article_text: str, max_items: int) -> str:
    return ARTICLE_ENTITY_EXTRACTION_PROMPT.format(
        article_text=article_text,
        max_items=max_items,
    )
