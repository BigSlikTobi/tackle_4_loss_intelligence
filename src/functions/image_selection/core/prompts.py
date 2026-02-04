"""Prompt templates and builders for image selection LLM queries.

This module contains enhanced prompts with visual intent classification
and negative prompting to reduce selection of images with overlays.
"""

from __future__ import annotations

from typing import Optional

# Words that strongly correlate with overlaid text, broadcast bugs, or thumbnails.
EXCLUSION_SUFFIX = (
    "-logo -watermark -thumbnail -screenshot -graphic -poster -meme "
    "-overlay -lower-third -infographic -chart -stats -card -trading "
    "-fantasy -highlight -replay -jersey -merchandise"
)

IMAGE_QUERY_SYSTEM_PROMPT = (
    "You are an expert at crafting precise image search queries for NFL football content. "
    "Your goal is to find a high-quality ACTION PHOTO or PORTRAIT that directly "
    "illustrates the article - NOT graphics, logos, trading cards, or composites. "
    "CRITICAL: Generate queries that will find REAL GAME PHOTOS from news sources. "
    "Return ONLY the search query string - no quotes, no explanations, no formatting."
)

# Enhanced prompt with visual intent classification and scene grounding
IMAGE_QUERY_PROMPT_TEMPLATE = (
    "Create an image search query (max {max_words} words) for this NFL article.\n\n"
    "STEP 1 - CLASSIFY the visual type needed:\n"
    "• GAME ACTION: plays, touchdowns, tackles, catches, interceptions\n"
    "• PORTRAIT: player headshots, press conferences, interviews\n"
    "• TEAM SHOT: sideline, huddle, celebration, locker room\n"
    "• VENUE: stadium exterior, field view, crowd shot\n\n"
    "STEP 2 - BUILD your query with these components:\n"
    "1. Full player name OR full team name (never abbreviations)\n"
    "2. 'NFL' keyword for sports context\n"
    "3. Scene descriptor matching visual type (field, podium, stadium, etc.)\n"
    "4. Exclusion terms: -graphic -logo -card -stats -highlight\n\n"
    "STEP 3 - EXAMPLES by article type:\n"
    "• Injury news: 'Patrick Mahomes NFL sideline injury -graphic -logo'\n"
    "• Game recap: 'Buffalo Bills Miami Dolphins NFL game action field -card'\n"
    "• Trade/signing: 'Davante Adams New York Jets press conference podium -logo'\n"
    "• Coach hire: 'Mike Vrabel New England Patriots head coach -graphic'\n"
    "• Team analysis: 'San Francisco 49ers NFL practice field -stats'\n\n"
    "AVOID:\n"
    "• Generic words: 'football', 'sports', 'news', 'update'\n"
    "• Abbreviations: 'KC' instead of 'Kansas City Chiefs'\n"
    "• Years unless essential for historical context\n"
    "• Anything that might return trading cards, graphics, or video thumbnails\n\n"
    "Article:\n{article_text}\n\n"
    "Search query:"
)

# Alternative prompts for different visual intents
ACTION_QUERY_PROMPT = (
    "Create an image search query (max {max_words} words) focused on GAME ACTION.\n"
    "Find photos of actual plays, touchdowns, tackles, or catches.\n\n"
    "Required components:\n"
    "1. Player full name or both team full names\n"
    "2. 'NFL' and action words: touchdown, catch, tackle, run, pass\n"
    "3. Exclusions: -graphic -logo -card -highlight\n\n"
    "Article:\n{article_text}\n\n"
    "Search query:"
)

PORTRAIT_QUERY_PROMPT = (
    "Create an image search query (max {max_words} words) focused on PORTRAIT/INTERVIEW.\n"
    "Find photos of player or coach at press conference, interview, or posed shot.\n\n"
    "Required components:\n"
    "1. Person's full name and team full name\n"
    "2. Context: 'press conference', 'interview', 'podium', 'portrait'\n"
    "3. Exclusions: -graphic -logo -card\n\n"
    "Article:\n{article_text}\n\n"
    "Search query:"
)


def build_image_query(core_query: str) -> str:
    """Append NFL context and exclusion terms to ensure football-related results."""
    core_query = " ".join(core_query.split())  # normalize spaces
    if not core_query:
        return "NFL American football " + EXCLUSION_SUFFIX.lstrip()
    
    # Ensure NFL context is present
    query_lower = core_query.lower()
    if "nfl" not in query_lower and "football" not in query_lower:
        core_query = f"{core_query} NFL American football"
    
    # Check if query already has exclusions
    if "-" in core_query:
        return core_query
    
    return f"{core_query} {EXCLUSION_SUFFIX}"


def build_image_query_prompt(
    article_text: str,
    *,
    max_words: int,
    template: Optional[str] = None,
    visual_intent: Optional[str] = None,
) -> str:
    """Format the article text using the provided or default image query template.
    
    Args:
        article_text: The article content to generate a query for.
        max_words: Maximum words allowed in the query.
        template: Optional custom prompt template.
        visual_intent: Optional visual intent type ('action', 'portrait', 'team').
    """
    # Select template based on visual intent
    if template:
        selected_template = template
    elif visual_intent == "action":
        selected_template = ACTION_QUERY_PROMPT
    elif visual_intent == "portrait":
        selected_template = PORTRAIT_QUERY_PROMPT
    else:
        selected_template = IMAGE_QUERY_PROMPT_TEMPLATE
    
    # Truncate article to avoid token limits
    truncated_text = article_text[:2500]
    
    return selected_template.format(
        article_text=truncated_text,
        max_words=max_words,
    )
