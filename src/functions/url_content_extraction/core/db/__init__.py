"""Database layer for the facts schema.

`FactsReader` and `FactsWriter` are the single source of truth for
`news_facts`, `facts_embeddings`, and the article-level pooled entries in
`story_embeddings`. Any new code touching these tables should use them;
see `core/facts/storage.py` for the older function-level API kept for
backwards compatibility with `extract_facts_cli`.
"""

from .ephemeral import EphemeralContentReader, EphemeralContentWriter
from .reader import FactsReader
from .writer import FactsWriter

__all__ = [
    "EphemeralContentReader",
    "EphemeralContentWriter",
    "FactsReader",
    "FactsWriter",
]
