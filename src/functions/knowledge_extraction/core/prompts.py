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
    You are an expert NFL analyst specialized in entity extraction. Your task is to extract ALL NFL entities from this story summary with COMPREHENSIVE COVERAGE and disambiguation information.

    **CRITICAL INSTRUCTIONS - READ CAREFULLY:**
    
    1. **EXTRACT ALL ENTITIES** - Do not skip entities just because you lack some context. Extract everything you can identify.
    2. **READ THE ENTIRE TEXT** - Scan through the complete summary to find ALL players, teams, and games mentioned.
    3. **PRIORITIZE COMPLETENESS** - It's better to extract an entity with partial information than to miss it entirely.
    4. **PROVIDE DISAMBIGUATION WHEN POSSIBLE** - Include position, team, or other identifying information whenever available in the text.

    ═══════════════════════════════════════════════════════════════════════════════

    **ENTITY TYPE 1: TEAMS**
    
    **ALWAYS EXTRACT ALL TEAM MENTIONS - This is the highest priority.**
    
    Teams can appear in many forms:
    - Full name: "New York Jets", "Kansas City Chiefs", "Indianapolis Colts"
    - City/location only: "New York", "Indianapolis" (when clearly referring to the team)
    - Nickname only: "Jets", "Chiefs", "Colts"
    - Possessive: "Jets'", "Chiefs'", "team's"
    - Contextual: "the team", "the organization" (when context makes it clear which team)
    
    **How to extract:**
    - mention_text: Use the exact text from the summary (e.g., "New York Jets", "Jets", "Indianapolis")
    - team_name: Full team name (e.g., "New York Jets", "Indianapolis Colts")
    - team_abbr: Standard NFL abbreviation if known (e.g., "NYJ", "IND", "KC")
    - confidence: 0.95-1.0 for explicit mentions, 0.7-0.9 for contextual references
    
    **Examples:**
    ✅ "New York Jets General Manager..." → {{"type": "team", "mention_text": "New York Jets", "team_name": "New York Jets", "team_abbr": "NYJ", "confidence": 1.0}}
    ✅ "...the Jets received..." → {{"type": "team", "mention_text": "Jets", "team_name": "New York Jets", "team_abbr": "NYJ", "confidence": 0.95}}
    ✅ "...sending them to Indianapolis" → {{"type": "team", "mention_text": "Indianapolis", "team_name": "Indianapolis Colts", "team_abbr": "IND", "confidence": 0.90}}
    ✅ "the team's long-term success" → {{"type": "team", "mention_text": "the team", "team_name": "New York Jets", "team_abbr": "NYJ", "confidence": 0.85}}

    ═══════════════════════════════════════════════════════════════════════════════

    **ENTITY TYPE 2: PLAYERS**
    
    **EXTRACT ALL PLAYER MENTIONS - Include as much disambiguation info as available.**
    
    A player mention requires:
    - REQUIRED: Player name (full name or last name)
    - RECOMMENDED: Position (QB, RB, WR, TE, CB, DT, LB, etc.) AND/OR Team
    - OPTIONAL: Additional context (draft info, accolades, role)
    
    **Extraction Guidelines:**
    - If a player has BOTH name AND position/team → Extract with high confidence (0.85-1.0)
    - If a player has ONLY a name but is prominent in context → Extract with medium confidence (0.70-0.85)
    - Include position info from descriptors: "cornerback Sauce Gardner" → position: "CB"
    - Include position from titles/roles: "All-Pro defensive tackle" → position: "DT"
    - Look for team context throughout the text to associate players with teams
    
    **How to extract:**
    - mention_text: Exact name as it appears (e.g., "Quinnen Williams", "Sauce Gardner", "Breece Hall")
    - position: NFL position abbreviation (QB, RB, WR, TE, CB, DT, DE, LB, S, K, P, etc.)
    - team_name: Full team name if mentioned or can be inferred (e.g., "New York Jets")
    - team_abbr: Team abbreviation if known (e.g., "NYJ")
    - context: Brief note about the player's role, accolades, or relevance (optional but helpful)
    - confidence: 0.90-1.0 with position+team, 0.75-0.90 with position OR team, 0.70-0.80 name only
    - rank: Importance ranking (1=primary/main subject, 2=important mention, 3+=minor mention)
    
    **Examples:**
    ✅ "cornerback Sauce Gardner" → {{"type": "player", "mention_text": "Sauce Gardner", "position": "CB", "team_name": "New York Jets", "team_abbr": "NYJ", "context": "two-time All-Pro", "confidence": 0.95}}
    ✅ "defensive tackle Quinnen Williams" → {{"type": "player", "mention_text": "Quinnen Williams", "position": "DT", "team_name": "New York Jets", "team_abbr": "NYJ", "context": "2022 All-Pro", "confidence": 0.95}}
    ✅ "receiver Adonai Mitchell" → {{"type": "player", "mention_text": "Adonai Mitchell", "position": "WR", "confidence": 0.85}}
    ✅ "Breece Hall" (mentioned as important player) → {{"type": "player", "mention_text": "Breece Hall", "team_name": "New York Jets", "team_abbr": "NYJ", "confidence": 0.80}}
    ✅ "General Manager Darren Mougey" → {{"type": "player", "mention_text": "Darren Mougey", "context": "General Manager", "team_name": "New York Jets", "team_abbr": "NYJ", "confidence": 0.85}}
    
    **Why we extract with partial information:**
    - "Quinnen Williams" appears with "defensive tackle" → We have name + position, extract it!
    - Context mentions "Jets" earlier → We can infer team association
    - Better to extract and let fuzzy matching resolve than to miss the entity entirely

    ═══════════════════════════════════════════════════════════════════════════════

    **ENTITY TYPE 3: GAMES**
    
    **EXTRACT SPECIFIC GAME REFERENCES when matchups are clearly described.**
    
    Games require:
    - Clear matchup between two teams
    - Optional: Week, date, playoff round, or other identifying context
    
    **Examples:**
    ✅ "Bills vs Chiefs Week 6" → {{"type": "game", "mention_text": "Bills vs Chiefs Week 6", "teams": ["Bills", "Chiefs"], "context": "Week 6", "confidence": 0.95}}
    ✅ "Super Bowl LVIII" → {{"type": "game", "mention_text": "Super Bowl LVIII", "teams": [], "context": "Super Bowl LVIII", "confidence": 1.0}}
    
    ═══════════════════════════════════════════════════════════════════════════════

    **EXTRACTION PROCESS:**
    
    1. **First Pass - Teams**: Identify ALL team mentions (full names, nicknames, contextual references)
    2. **Second Pass - Players**: Identify ALL player names, then scan the text for position/team/context clues
    3. **Third Pass - Games**: Identify any specific game matchups mentioned
    4. **Fourth Pass - Cross-reference**: Link players to teams based on story context
    5. **Fifth Pass - Ranking**: Assign rank based on prominence (1=main subject, 2=important, 3+=supporting)
    6. **Final Check**: Have you extracted EVERY team and player mentioned? Review the text one more time.
    
    **RANKING SYSTEM:**
    - Rank 1: Primary entities - the main subjects of the story (traded players, team making the move, etc.)
    - Rank 2: Secondary entities - important supporting entities (receiving team, mentioned players)
    - Rank 3+: Minor entities - mentioned but not central to the story
    
    ═══════════════════════════════════════════════════════════════════════════════

    **OUTPUT FORMAT:**
    
    Return up to {max_items} entities in JSON format, **ORDERED BY RANK** (rank 1 first, then 2, then 3, etc.):
    
    {{
      "entities": [
        {{
          "type": "team",
          "mention_text": "New York Jets",
          "team_name": "New York Jets",
          "team_abbr": "NYJ",
          "confidence": 1.0,
          "rank": 1
        }},
        {{
          "type": "player",
          "mention_text": "Quinnen Williams",
          "position": "DT",
          "team_name": "New York Jets",
          "team_abbr": "NYJ",
          "context": "2022 All-Pro defensive tackle",
          "confidence": 0.95,
          "rank": 1
        }},
        {{
          "type": "team",
          "mention_text": "Indianapolis",
          "team_name": "Indianapolis Colts",
          "team_abbr": "IND",
          "confidence": 0.90,
          "rank": 2
        }},
        {{
          "type": "player",
          "mention_text": "Breece Hall",
          "team_name": "New York Jets",
          "team_abbr": "NYJ",
          "confidence": 0.80,
          "rank": 3
        }}
      ]
    }}

    ═══════════════════════════════════════════════════════════════════════════════

    **STORY SUMMARY:**

    {summary_text}

    ═══════════════════════════════════════════════════════════════════════════════

    **YOUR RESPONSE (JSON ONLY):**
    
    Before responding, ask yourself:
    1. Did I extract EVERY team mentioned? (Check for full names, nicknames, city names)
    2. Did I extract EVERY player mentioned? (Check for full names, last names, role descriptions)
    3. Did I include as much disambiguation info as possible from the text?
    4. Did I assign appropriate ranks (1=primary, 2=secondary, 3+=minor)?
    5. Are entities ordered by rank in my response?
    
    Now provide your JSON response:
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
