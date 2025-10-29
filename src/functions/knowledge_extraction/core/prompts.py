"""Prompt builders for knowledge extraction LLM workflows."""

from __future__ import annotations

from textwrap import dedent

TOPIC_EXTRACTION_PROMPT_TEMPLATE = dedent(
    """
    You are an expert NFL analyst specialized in topic extraction. Classify the key NFL themes from this story summary using the STANDARDIZED topic categories below.

    **Allowed Topic Categories (return the EXACT category names):**
    1. Quarterback Performance & Analysis
    2. Running Back & Rushing Game
    3. Wide Receiver & Passing Game
    4. Defense & Turnovers
    5. Coaching & Play Calling
    6. Injuries & Player Health
    7. Team Performance & Trends
    8. Season Outlook & Predictions
    9. Rookies & Emerging Players
    10. Draft & College Prospects
    11. Trades, Signings & Roster Moves
    12. Contracts & Cap Management
    13. Game Analysis & Highlights
    14. Statistics & Rankings
    15. Fantasy Football Impact
    16. Offseason & Training Camp
    17. Special Teams & Kicking Game
    18. Refereeing & Rules
    19. Player Profiles & Interviews
    20. Team Culture & Leadership
    21. League News & Administration
    22. Off-Field & Lifestyle
    23. Media & Fan Reactions

    **Guidelines:**
    - Return only categories from the list above. Do NOT invent new categories.
    - If multiple categories apply, include each as a separate topic ranked by importance.
    - Provide at most {max_items} categories, ordered by rank.
    - Avoid player or team names (handled separately as entities).
    - Keep confidence between 0 and 1 with two decimal precision.

    **RANKING SYSTEM:**
    - Rank 1: Primary topic(s) - the main theme/focus of the story
    - Rank 2: Secondary topics - important supporting themes
    - Rank 3+: Minor topics - mentioned but not central

    Return in JSON format, **ORDERED BY RANK** (rank 1 first, then 2, then 3, etc.):

    {{
      "topics": [
        {{
          "topic": "quarterback performance & analysis",
          "confidence": 0.95,
          "rank": 1
        }},
        {{
          "topic": "injuries & player health",
          "confidence": 0.90,
          "rank": 1
        }},
        {{
          "topic": "team performance & trends",
          "confidence": 0.85,
          "rank": 2
        }}
      ]
    }}

    **Story Summary:**

    {summary_text}

    **Your Response (JSON only):**
    """
).strip()

ENTITY_EXTRACTION_PROMPT_TEMPLATE = dedent(
    """
    You are an expert NFL analyst specialized in entity extraction. Your task is to extract NFL entities from this story summary with STRICT DISAMBIGUATION REQUIREMENTS.

    **CRITICAL: Player Disambiguation Rules**
    For EVERY player mention, you MUST provide AT LEAST 2 identifying hints:
    1. Player name (required)
    2. Position (QB, RB, WR, TE, etc.) OR Team (abbreviation like BUF, KC, or full name)

    **Why this matters:**
    - Multiple players can have the same name (e.g., Josh Allen QB vs Josh Allen LB)
    - Without disambiguation, we cannot accurately resolve players to database records
    - ONLY extract a player if you can identify AT LEAST 2 hints from the text

    **Example Valid Extractions:**
    ✅ "Josh Allen" + "quarterback" → mention_text: "Josh Allen", position: "QB"
    ✅ "Josh Allen" + "Bills" → mention_text: "Josh Allen", team_name: "Bills"
    ✅ "Mahomes" + "Chiefs QB" → mention_text: "Mahomes", position: "QB", team_abbr: "KC"
    ✅ "Travis Kelce" + "tight end" → mention_text: "Travis Kelce", position: "TE"
    ✅ "Allen" + "Bills QB" → mention_text: "Allen", position: "QB", team_name: "Bills"

    **Example INVALID Extractions (DO NOT EXTRACT):**
    ❌ "Josh Allen" with no position or team mentioned → SKIP this player
    ❌ "Allen" alone without position or team → SKIP - needs disambiguation
    ❌ "Smith" with no position or team → SKIP this player
    ❌ "the quarterback" with no name → SKIP this reference

    **Entity Types to Extract:**

    1. **PLAYERS**: Any NFL player mentioned WITH 2+ identifying hints
       - REQUIRED: Player name (full or last name)
       - REQUIRED: Position (QB, RB, WR, TE, etc.) OR Team (abbreviation/full name)
       - OPTIONAL: Additional context for confidence
       - If you cannot find 2+ hints, DO NOT extract the player

    2. **TEAMS**: Any NFL team mentioned
       - Use both full names and abbreviations: Kansas City Chiefs, Chiefs, KC
       - Include possessive forms: "Chiefs'", "Chargers'"

    3. **GAMES**: Specific game references
       - Mention exact matchup (e.g., "Bills vs Chiefs Week 6" or "Super Bowl LVIII")
       - Include context like week, round, or playoff stage if available

    **Output Requirements:**
    - Provide at most {max_items} entities ordered by relevance.
    - Each entity must include "type" (player|team|game), "mention_text", and "confidence" (0-1).
    - For PLAYERS include at least two of: "position", "team_abbr", "team_name".
    - For TEAMS include "team_name" and "team_abbr" if available.
    - For GAMES include "teams" (array of team names/abbrs) and optional "context".

    **Story Summary:**

    {summary_text}

    **Your Response (JSON only):**
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
