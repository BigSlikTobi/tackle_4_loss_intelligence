"""Fact extraction module for NFL article content.

Provides components for extracting atomic facts from article text:
- prompts: Fact extraction prompt templates
- parser: JSON response parsing
- filter: Non-story fact filtering

Database operations used to live here (``storage``) but were consolidated
into ``core/db/{reader,writer}.py`` — import ``FactsReader`` / ``FactsWriter``
from there instead.
"""

from .prompts import FACT_PROMPT, FACT_PROMPT_VERSION
from .parser import parse_fact_response
from .filter import is_valid_nfl_fact, filter_story_facts

__all__ = [
    "FACT_PROMPT",
    "FACT_PROMPT_VERSION",
    "parse_fact_response",
    "is_valid_nfl_fact",
    "filter_story_facts",
]
