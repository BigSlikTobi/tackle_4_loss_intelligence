"""Compat shim — JobStore moved to :mod:`src.shared.jobs.store`.

This module re-exports it (with the article-knowledge-extraction service
name baked into a default-bound subclass) so existing imports keep working.
"""

from __future__ import annotations

from src.shared.jobs.contracts import JobStatus  # noqa: F401  (legacy re-export)
from src.shared.jobs.store import JobStore as _GenericJobStore
from src.shared.jobs.store import build_client  # noqa: F401  (legacy re-export)

from ..config import SupabaseConfig

DEFAULT_SERVICE = "article_knowledge_extraction"


class JobStore(_GenericJobStore):
    """JobStore subclass that defaults ``service`` for this module."""

    def __init__(
        self,
        config: SupabaseConfig,
        client=None,
        *,
        service: str = DEFAULT_SERVICE,
    ):
        super().__init__(config, client=client, service=service)
