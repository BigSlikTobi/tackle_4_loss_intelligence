"""Fact extraction module for NFL article content.

Provides components for extracting atomic facts from article text:
- prompts: Fact extraction prompt templates
- parser: JSON response parsing
- filter: Non-story fact filtering
- storage: Database operations for facts
"""

from .prompts import FACT_PROMPT, FACT_PROMPT_VERSION
from .parser import parse_fact_response
from .filter import is_valid_nfl_fact, filter_story_facts
from .storage import (
    store_facts,
    fetch_existing_fact_ids,
    remove_non_story_facts_from_db,
    create_fact_embeddings,
    bulk_check_embeddings,
)

__all__ = [
    "FACT_PROMPT",
    "FACT_PROMPT_VERSION",
    "parse_fact_response",
    "is_valid_nfl_fact",
    "filter_story_facts",
    "store_facts",
    "fetch_existing_fact_ids",
    "remove_non_story_facts_from_db",
    "create_fact_embeddings",
    "bulk_check_embeddings",
]
