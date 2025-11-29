"""Fact extraction prompt templates."""

from datetime import datetime, timezone

FACT_PROMPT_VERSION = "facts-v1"

FACT_PROMPT = """ASK: Extract discrete facts from the article. Closed world. No inferences.
Current Date: {current_date}

RULES
- Use only the information explicitly stated in the text.
- Do not infer motivations, causes, consequences, or relationships.
- Do not add external knowledge.
- Maintain the original order of the article.
- Keep each statement short, specific, and self-contained.
- Exactly ONE factual claim per statement. Avoid using "and" to combine different events.
- Prefer repeating full player names, team names, and entities instead of pronouns when it improves clarity.
- Preserve all numbers, dates, scores, contract amounts, and durations exactly as written.
- Ignore navigation menus, cookie banners, share buttons, and other website boilerplate. Only use the main article content.
- Include all player names, team names, dates, trades, quotes, contract references, injuries, and statements about future plans that are explicitly stated.
- If something is not in the article, do NOT mention it.

CRITICAL QUALITY RULES:
1. TIMELINESS: Ensure all temporal statements are anchored to the Current Date ({current_date}).
   - BAD: "Joe Flacco turns 40 next year."
   - GOOD: "Joe Flacco will turn 40 in 2026." (if context allows) or "Joe Flacco turns 40 on [Specific Date]."
   - BAD: "Lamp is starting his 4th season."
   - GOOD: "Lamp is starting his 4th season in 2025."
2. NO META-INFO: EXCLUDE facts about the author, source, publication time, or media outlet.
   - BAD: "Tristan H. Cockcroft wrote the article."
   - BAD: "The article suggests..."
3. NO GENERALITIES: EXCLUDE general statements, opinions, platitudes, or vague commentary.
   - BAD: "Fantasy football lineup decisions can be challenging."
   - BAD: "Losses are costing seasons."
4. SPECIFIC SUBJECTS: ALWAYS specify the subject. Replace "The organization", "The team", or pronouns with the specific team or player name.
   - BAD: "The organization was looking for a path to turn things around."
   - GOOD: "The [Team Name] was looking for a path to turn things around."
5. LEANNESS: Optimize for leanness. Extract only significant, concrete facts. Avoid verbose filler.

INVALID EXAMPLES (DO NOT DO):
- "Gardner was traded to Team X" when not stated → INVALID inference
- "Johnson demanded a trade" if not stated → INVALID inference
- Adding any commentary, opinions, or analysis.

OUTPUT FORMAT (JSON only):
{{
  "facts": [
    "fact 1",
    "fact 2",
    "fact 3"
  ]
}}

Output ONLY valid JSON. No extra text, no comments, no explanations.
"""


def get_formatted_prompt() -> str:
    """Get the fact prompt with current date filled in.
    
    Returns:
        Formatted prompt string
    """
    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return FACT_PROMPT.format(current_date=current_date)
