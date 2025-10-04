"""Database access layer for story embeddings."""

from .reader import SummaryReader
from .writer import EmbeddingWriter

__all__ = ["SummaryReader", "EmbeddingWriter"]
