"""Filter non-story facts from extracted content."""

from __future__ import annotations

import logging
import re
from typing import List, Sequence, Tuple

logger = logging.getLogger(__name__)

# Patterns that indicate non-story content (author bios, navigation, metadata)
NON_STORY_PATTERNS = [
    # Author/journalist titles and affiliations
    r'\b(is a|is an)\b.{0,30}\b(reporter|writer|journalist|correspondent|analyst|contributor|editor|columnist)\b.{0,20}\b(for|at|with)\b.{0,20}\b(espn|nfl\.com|cbs|fox|nbc)',
    r'\b(reporter|writer|journalist|correspondent|analyst|contributor|editor|columnist)\b.{0,20}\b(for|at|with)\b.{0,20}\b(espn|nfl\.com|cbs|fox|nbc)',
    r'\b(senior|national|lead|staff)\b.{0,20}\b(reporter|writer|journalist|correspondent|analyst)',
    
    # ESPN style: "Name covers the Team at ESPN"
    r'\b(covers|covering)\b.{0,50}\b(at espn|for espn|at nfl\.com|for nfl\.com)',
    r'\b(covers|covering)\b.{0,20}\b(beat|nfl|sports)',
    r'\bcovers\b.{0,20}\b(entire league|whole league|league-wide)',
    r'\bcovered the\b.{0,30}\b(for more than|since \d{4})',
    
    # Joining/employment statements
    r'\b(joining|joined)\b.{0,20}\b(espn|nfl\.com|cbs|fox|nbc)',
    r'\bassists with\b.{0,30}\b(coverage|draft|reporting)',
    
    # Contribution/author bio snippets
    r'\bcontributes to\b.{0,50}\b(espn|nfl live|get up|sportscenter|countdown|radio)',
    r'\bis (the )?author of\b',
    r'\bis (the )?co-author of\b',
    r'\bauthor of two published novels\b',
    
    # Professional affiliations
    r'\bmember of the\b.{0,50}\b(board of selectors|hall of fame|association)',
    
    # Contact/social media
    r'\b(follow|contact).{0,20}\b(twitter|facebook|instagram|linkedin|email)',
    
    # Social media and engagement
    r'\b(follow|subscribe|sign up|join|get).{0,30}\b(newsletter|updates|alerts)',
    r'@\w+',  # Social media handles
    r'\b(like|share|comment|retweet)\b',
    
    # Website navigation and metadata
    r'\b(click here|read more|view all|see also|related stories)',
    r'\b(photo credit|image courtesy|getty images)',
    r'\b(copyright|©|all rights reserved)',
    r'\b(terms of service|privacy policy)',
    
    # Advertisement and promotional
    r'\b(advertisement|sponsored|promoted)\b',
    r'\b(download|install) (app|application)',
    
    # Very short or generic statements (likely boilerplate)
    r'^\w{1,3}$',  # Single short words
]


def is_valid_nfl_fact(fact_text: str) -> bool:
    """Check if a fact is valid NFL story content.
    
    Filters out author bios, navigation elements, social media, 
    and other non-story content.
    
    Args:
        fact_text: The fact text to validate
        
    Returns:
        True if the fact is valid story content
    """
    if not fact_text or not isinstance(fact_text, str):
        return False
    
    fact_lower = fact_text.lower()
    
    for pattern in NON_STORY_PATTERNS:
        if re.search(pattern, fact_lower, re.IGNORECASE):
            logger.debug("Filtered non-story fact: %s", fact_text[:100])
            return False
    
    # Must have minimum length (very short facts are often metadata)
    if len(fact_text) < 15:
        return False
    
    return True


def filter_story_facts(facts: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Split facts into valid story facts and rejected entries.
    
    Args:
        facts: Sequence of fact strings to filter
        
    Returns:
        Tuple of (valid_facts, rejected_facts)
    """
    valid: List[str] = []
    rejected: List[str] = []

    for fact in facts:
        if is_valid_nfl_fact(fact):
            valid.append(fact)
        else:
            rejected.append(fact)

    return valid, rejected
