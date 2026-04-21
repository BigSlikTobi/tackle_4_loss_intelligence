"""Paginated read helpers for the facts schema.

Centralizes the `news_facts` / `facts_embeddings` / `story_embeddings` read
operations that used to live in three places (realtime post-processor, batch
result processor, and `facts/storage`). Every multi-row read uses Supabase's
`.range(offset, offset + page_size - 1)` pattern to respect the 1000-row cap.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from ..facts.prompts import FACT_PROMPT_VERSION

logger = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 1000
_DEFAULT_CHUNK_SIZE = 100


class FactsReader:
    """Read-only accessor around the facts schema for a given Supabase client."""

    def __init__(
        self,
        client: Any,
        *,
        prompt_version: str = FACT_PROMPT_VERSION,
    ) -> None:
        self.client = client
        self.prompt_version = prompt_version

    # ------------------------------------------------------------------
    # news_facts
    # ------------------------------------------------------------------

    def fetch_existing_fact_ids(
        self,
        news_url_id: str,
        *,
        page_size: int = _DEFAULT_PAGE_SIZE,
    ) -> List[str]:
        """Return all fact IDs stored for ``news_url_id`` (this prompt version)."""
        fact_ids: List[str] = []
        offset = 0
        while True:
            response = (
                self.client.table("news_facts")
                .select("id")
                .eq("news_url_id", news_url_id)
                .eq("prompt_version", self.prompt_version)
                .order("id", desc=True)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            rows = getattr(response, "data", []) or []
            fact_ids.extend(row.get("id") for row in rows if row.get("id") is not None)
            if len(rows) < page_size:
                break
            offset += page_size
        return fact_ids

    def check_existing_facts(
        self,
        article_ids: Sequence[str],
        *,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        page_size: int = _DEFAULT_PAGE_SIZE,
    ) -> Set[str]:
        """Return the subset of ``article_ids`` that already have facts stored."""
        existing: Set[str] = set()
        ids = list(article_ids)
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            offset = 0
            while True:
                response = (
                    self.client.table("news_facts")
                    .select("news_url_id")
                    .in_("news_url_id", chunk)
                    .eq("prompt_version", self.prompt_version)
                    .range(offset, offset + page_size - 1)
                    .execute()
                )
                rows = getattr(response, "data", []) or []
                if not rows:
                    break
                existing.update(
                    row.get("news_url_id") for row in rows if row.get("news_url_id")
                )
                if set(chunk).issubset(existing):
                    break
                if len(rows) < page_size:
                    break
                offset += page_size
        return existing

    def fetch_fact_texts(
        self,
        fact_ids: Sequence[str],
        *,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
    ) -> Dict[str, str]:
        """Return ``{fact_id: fact_text}`` for the supplied IDs."""
        texts: Dict[str, str] = {}
        ids = list(fact_ids)
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            response = (
                self.client.table("news_facts")
                .select("id,fact_text")
                .in_("id", chunk)
                .execute()
            )
            rows = getattr(response, "data", []) or []
            for row in rows:
                if row.get("id") and row.get("fact_text") is not None:
                    texts[row["id"]] = row["fact_text"]
        return texts

    def fetch_fact_ids_for_articles(
        self,
        article_ids: Sequence[str],
        *,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
    ) -> List[str]:
        """Flat list of fact IDs across the supplied articles (any prompt version)."""
        out: List[str] = []
        ids = list(article_ids)
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            response = (
                self.client.table("news_facts")
                .select("id")
                .in_("news_url_id", chunk)
                .execute()
            )
            rows = getattr(response, "data", []) or []
            out.extend(row.get("id") for row in rows if row.get("id"))
        return out

    # ------------------------------------------------------------------
    # facts_embeddings / story_embeddings
    # ------------------------------------------------------------------

    def check_existing_embeddings(
        self,
        fact_ids: Sequence[str],
        *,
        chunk_size: int = _DEFAULT_PAGE_SIZE,
    ) -> Set[str]:
        """Return the subset of fact IDs that already have embeddings."""
        ids = list(fact_ids)
        if not ids:
            return set()
        existing: Set[str] = set()
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            response = (
                self.client.table("facts_embeddings")
                .select("news_fact_id")
                .in_("news_fact_id", chunk)
                .execute()
            )
            rows = getattr(response, "data", []) or []
            existing.update(
                row.get("news_fact_id") for row in rows if row.get("news_fact_id")
            )
        return existing

    def fetch_fact_embeddings(
        self,
        fact_ids: Sequence[str],
        *,
        chunk_size: int = _DEFAULT_PAGE_SIZE,
    ) -> List[List[float]]:
        """Return embedding vectors for the supplied fact IDs (parse-safe)."""
        import json

        vectors: List[List[float]] = []
        ids = list(fact_ids)
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            response = (
                self.client.table("facts_embeddings")
                .select("embedding_vector")
                .in_("news_fact_id", chunk)
                .execute()
            )
            rows = getattr(response, "data", []) or []
            for row in rows:
                vector = row.get("embedding_vector")
                if isinstance(vector, str):
                    try:
                        vector = json.loads(vector.strip("[]"))
                    except Exception:
                        continue
                if isinstance(vector, list) and vector:
                    vectors.append(vector)
        return vectors

    def pooled_embedding_exists(self, news_url_id: str) -> bool:
        """Return True when a ``fact_pooled`` story embedding already exists."""
        response = (
            self.client.table("story_embeddings")
            .select("id")
            .eq("news_url_id", news_url_id)
            .eq("embedding_type", "fact_pooled")
            .limit(1)
            .execute()
        )
        return bool(getattr(response, "data", []) or [])
