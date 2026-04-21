"""Unified writer for the facts schema.

Consolidates what used to be three parallel implementations
(``facts/storage``, ``facts_batch.result_processor``, and
``post_processors.fact_extraction``) behind a single API. Callers construct
a ``FactsWriter`` with a Supabase client and invoke the method matching
their workflow (single article vs. bulk batch vs. force re-extraction).

The writer never mutates OpenAI module globals; embedding generation is
done through a caller-supplied ``openai.OpenAI`` client.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..facts.prompts import FACT_PROMPT_VERSION

logger = logging.getLogger(__name__)

_DEFAULT_CHUNK_SIZE = 100


def _calculate_difficulty_from_facts(facts_count: int) -> str:
    """Mirror of the heuristic in the batch result processor.

    Kept here so every caller lands in the same bucket without needing to
    reach into the result processor class.
    """
    if facts_count < 10:
        return "easy"
    if facts_count <= 30:
        return "medium"
    return "hard"


class FactsWriter:
    """Write-side helper around the facts schema for a Supabase client."""

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

    def insert_facts(
        self,
        facts_by_article: Dict[str, List[str]],
        model: str,
        *,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
    ) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
        """Bulk insert facts.

        Returns ``(ids_by_article, texts_by_id)``. ``texts_by_id`` lets
        embedding creation skip the redundant ``SELECT`` against rows we
        just wrote.

        If the DB returns a row count that diverges from the input chunk
        size we skip ID attribution for that chunk rather than corrupt the
        downstream mapping.
        """
        all_records: List[Dict[str, Any]] = []
        record_to_article: List[str] = []
        record_texts: List[str] = []

        for article_id, facts in facts_by_article.items():
            for fact in facts:
                all_records.append(
                    {
                        "news_url_id": article_id,
                        "fact_text": fact,
                        "llm_model": model,
                        "prompt_version": self.prompt_version,
                    }
                )
                record_to_article.append(article_id)
                record_texts.append(fact)

        if not all_records:
            return {}, {}

        result_ids: Dict[str, List[str]] = {aid: [] for aid in facts_by_article}
        texts_by_id: Dict[str, str] = {}
        record_idx = 0

        for i in range(0, len(all_records), chunk_size):
            chunk = all_records[i : i + chunk_size]
            try:
                response = self.client.table("news_facts").insert(chunk).execute()
                data = getattr(response, "data", []) or []

                if len(data) != len(chunk):
                    logger.error(
                        "Insert returned %d rows for chunk of %d; skipping ID "
                        "attribution to avoid desync",
                        len(data),
                        len(chunk),
                    )
                else:
                    for offset, row in enumerate(data):
                        if isinstance(row, dict) and row.get("id"):
                            article_id = record_to_article[record_idx + offset]
                            result_ids[article_id].append(row["id"])
                            texts_by_id[row["id"]] = record_texts[record_idx + offset]

                record_idx += len(chunk)

            except Exception as exc:
                logger.error("Failed to insert facts chunk: %s", exc)
                record_idx += len(chunk)

        return result_ids, texts_by_id

    def insert_facts_for_article(
        self,
        news_url_id: str,
        facts: Sequence[str],
        model: str,
    ) -> Tuple[List[str], Dict[str, str]]:
        """Single-article convenience wrapper over :meth:`insert_facts`."""
        if not facts:
            return [], {}
        ids_by_article, texts_by_id = self.insert_facts(
            {news_url_id: list(facts)}, model
        )
        return ids_by_article.get(news_url_id, []), texts_by_id

    # ------------------------------------------------------------------
    # facts_embeddings
    # ------------------------------------------------------------------

    def insert_fact_embeddings(
        self,
        records: List[Dict[str, Any]],
        *,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
    ) -> int:
        """Raw bulk insert into ``facts_embeddings``. Returns rows written."""
        if not records:
            return 0
        total = 0
        for i in range(0, len(records), chunk_size):
            chunk = records[i : i + chunk_size]
            try:
                response = (
                    self.client.table("facts_embeddings").insert(chunk).execute()
                )
                total += len(getattr(response, "data", []) or [])
            except Exception as exc:
                logger.error("Failed to insert fact embeddings chunk: %s", exc)
        return total

    # ------------------------------------------------------------------
    # story_embeddings (article-level pooled)
    # ------------------------------------------------------------------

    def insert_pooled_embedding(
        self,
        news_url_id: str,
        vectors: Sequence[Sequence[float]],
        model: str,
    ) -> bool:
        """Compute and insert a ``fact_pooled`` article embedding.

        Returns ``True`` when a row was inserted, ``False`` if the input
        was empty (no write attempted).
        """
        usable: List[List[float]] = [list(v) for v in vectors if v]
        if not usable:
            return False

        dimension = len(usable[0])
        totals = [0.0] * dimension
        counted = 0
        for vector in usable:
            if len(vector) != dimension:
                continue
            counted += 1
            for idx, val in enumerate(vector):
                totals[idx] += float(val)
        if counted == 0:
            return False
        averaged = [val / counted for val in totals]

        try:
            self.client.table("story_embeddings").insert(
                {
                    "news_url_id": news_url_id,
                    "embedding_vector": averaged,
                    "model_name": model,
                    "embedding_type": "fact_pooled",
                    "scope": "article",
                    "primary_topic": None,
                    "primary_team": None,
                }
            ).execute()
            return True
        except Exception as exc:
            logger.error("Failed to insert pooled embedding for %s: %s", news_url_id, exc)
            return False

    # ------------------------------------------------------------------
    # news_urls (stage tracking)
    # ------------------------------------------------------------------

    def mark_facts_extracted(
        self,
        facts_by_article: Dict[str, List[str]],
        *,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        now: Optional[datetime] = None,
    ) -> None:
        """Stamp ``facts_extracted_at`` + stats for multiple articles.

        Buckets by ``(facts_count, difficulty)`` and emits one UPDATE per
        bucket via ``.in_("id", [...])`` to avoid N sequential round-trips.
        """
        if not facts_by_article:
            return
        now_iso = (now or datetime.now(timezone.utc)).isoformat()

        buckets: Dict[Tuple[int, str], List[str]] = {}
        for article_id, facts in facts_by_article.items():
            facts_count = len(facts)
            difficulty = _calculate_difficulty_from_facts(facts_count)
            buckets.setdefault((facts_count, difficulty), []).append(article_id)

        for (facts_count, difficulty), article_ids in buckets.items():
            for i in range(0, len(article_ids), chunk_size):
                chunk = article_ids[i : i + chunk_size]
                try:
                    self.client.table("news_urls").update(
                        {
                            "facts_extracted_at": now_iso,
                            "facts_count": facts_count,
                            "article_difficulty": difficulty,
                        }
                    ).in_("id", chunk).execute()
                except Exception as exc:
                    logger.error(
                        "Failed to mark facts_extracted_at for bucket "
                        "(count=%d, difficulty=%s, %d articles): %s",
                        facts_count,
                        difficulty,
                        len(chunk),
                        exc,
                    )

    def mark_single_article_facts_extracted(
        self,
        news_url_id: str,
        *,
        backfill_content_extracted_at: bool = True,
        now: Optional[datetime] = None,
    ) -> None:
        """Realtime-path stamp: ``facts_extracted_at`` always, and optionally
        backfill ``content_extracted_at`` only when it's still NULL (so we
        don't overwrite a truer timestamp owned by an upstream stage)."""
        now_iso = (now or datetime.now(timezone.utc)).isoformat()
        self.client.table("news_urls").update(
            {"facts_extracted_at": now_iso}
        ).eq("id", news_url_id).execute()
        if backfill_content_extracted_at:
            self.client.table("news_urls").update(
                {"content_extracted_at": now_iso}
            ).eq("id", news_url_id).is_("content_extracted_at", "null").execute()

    # ------------------------------------------------------------------
    # Force re-extraction (batch path only)
    # ------------------------------------------------------------------

    def delete_fact_data(
        self,
        article_ids: Sequence[str],
        *,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
    ) -> int:
        """Delete facts, embeddings, entity/topic links and story-level
        pooled embeddings for the supplied articles. Also resets the
        downstream stage timestamps on ``news_urls``.

        Returns the number of facts deleted.
        """
        ids = list(article_ids)
        if not ids:
            return 0

        # 1. collect all fact IDs
        all_fact_ids: List[str] = []
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            response = (
                self.client.table("news_facts")
                .select("id")
                .in_("news_url_id", chunk)
                .execute()
            )
            rows = getattr(response, "data", []) or []
            all_fact_ids.extend(row.get("id") for row in rows if row.get("id"))

        # 2. delete fact-scoped rows
        for i in range(0, len(all_fact_ids), chunk_size):
            chunk = all_fact_ids[i : i + chunk_size]
            self.client.table("facts_embeddings").delete().in_(
                "news_fact_id", chunk
            ).execute()
            self.client.table("news_fact_entities").delete().in_(
                "news_fact_id", chunk
            ).execute()
            self.client.table("news_fact_topics").delete().in_(
                "news_fact_id", chunk
            ).execute()
            self.client.table("news_facts").delete().in_("id", chunk).execute()

        # 3. delete article-scoped story embeddings + reset stage stamps
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            self.client.table("story_embeddings").delete().in_(
                "news_url_id", chunk
            ).execute()
            self.client.table("news_urls").update(
                {
                    "facts_extracted_at": None,
                    "facts_count": None,
                    "article_difficulty": None,
                    "knowledge_extracted_at": None,
                    "knowledge_error_count": 0,
                    "summary_created_at": None,
                }
            ).in_("id", chunk).execute()

        return len(all_fact_ids)
