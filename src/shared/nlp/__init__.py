"""Shared NLP utilities (NFL-aware entity resolution, fuzzy matching)."""

from src.shared.nlp.entity_resolver import EntityResolver
from src.shared.contracts.knowledge import ResolvedEntity

__all__ = ["EntityResolver", "ResolvedEntity"]
