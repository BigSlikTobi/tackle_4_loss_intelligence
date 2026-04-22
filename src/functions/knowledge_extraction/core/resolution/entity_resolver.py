"""Re-export shim for the shared EntityResolver.

Historical location of `EntityResolver` and `ResolvedEntity`. Both have moved
to `src/shared/nlp/` and `src/shared/contracts/knowledge.py` so the fact-level
and article-level knowledge-extraction modules can share them without
cross-module imports. This shim preserves the original import paths used by
existing call sites inside `knowledge_extraction`.
"""

from src.shared.contracts.knowledge import ResolvedEntity
from src.shared.nlp.entity_resolver import EntityResolver

__all__ = ["EntityResolver", "ResolvedEntity"]
