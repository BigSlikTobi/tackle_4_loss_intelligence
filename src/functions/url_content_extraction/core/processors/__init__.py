"""Backwards-compat re-export shim.

Processors moved to ``src.shared.processors``.
"""

from src.shared.processors import content_cleaner, metadata_extractor, text_deduplicator  # noqa: F401
