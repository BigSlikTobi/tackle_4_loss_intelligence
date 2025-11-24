"""Reader for story embeddings from the database."""

import logging
import json
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone

from src.shared.db import get_supabase_client

logger = logging.getLogger(__name__)


def parse_vector(vector_data) -> Optional[List[float]]:
    """
    Parse vector data from database format to Python list.
    
    Args:
        vector_data: Vector in various formats (string, list, etc.)
        
    Returns:
        List of floats, or None if invalid
    """
    if vector_data is None:
        return None
    
    # If already a list, return it
    if isinstance(vector_data, list):
        return vector_data
    
    # If string, try to parse
    if isinstance(vector_data, str):
        # PostgreSQL vector format: "[1.0, 2.0, 3.0]"
        try:
            # Remove brackets and split by comma
            if vector_data.startswith('[') and vector_data.endswith(']'):
                vector_str = vector_data[1:-1]
                return [float(x.strip()) for x in vector_str.split(',')]
            else:
                # Try JSON parsing
                return json.loads(vector_data)
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to parse vector: {e}")
            return None
    
    return None


class EmbeddingReader:
    """Reads fact-level embeddings joined with their parent news URLs."""

    def __init__(self, days_lookback: int = 14):
        """
        Initialize the embedding reader.
        
        Args:
            days_lookback: Number of days to look back for stories (default: 14)
        """
        self.client = get_supabase_client()
        self.days_lookback = days_lookback
    
    def _get_cutoff_date(self) -> str:
        """
        Get the cutoff date for filtering stories.
        
        Returns:
            ISO format datetime string for the cutoff date
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_lookback)
        return cutoff.isoformat()

    @staticmethod
    def _normalize_fact_embedding(record: Dict) -> Optional[Dict]:
        """Normalize a facts_embeddings record into a grouping-ready dict."""

        vector = parse_vector(record.get("embedding_vector"))
        news_fact = record.get("news_facts") or {}
        news_url_id = news_fact.get("news_url_id")

        if vector is None or news_url_id is None:
            return None

        return {
            "id": record.get("id"),
            "news_fact_id": record.get("news_fact_id"),
            "news_url_id": news_url_id,
            "embedding_vector": vector,
            "created_at": news_fact.get("created_at")
            or record.get("created_at"),
        }

    def _get_grouped_fact_ids(self) -> set:
        """Collect fact IDs that are already assigned to story groups."""

        grouped_fact_ids: set = set()
        page_size = 1000
        offset = 0
        max_batches = 15
        batches = 0

        while batches < max_batches:
            response = (
                self.client.table("story_group_members")
                .select("news_fact_id")
                .not_.is_("news_fact_id", "null")
                .range(offset, offset + page_size - 1)
                .execute()
            )

            if not response.data:
                break

            grouped_fact_ids.update(
                item.get("news_fact_id") for item in response.data if item.get("news_fact_id")
            )

            if len(response.data) < page_size:
                break

            offset += page_size
            batches += 1

        logger.info("Found %s already grouped facts", len(grouped_fact_ids))
        return grouped_fact_ids


    def fetch_ungrouped_embeddings(
        self,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Fetch fact embeddings for stories not yet assigned to a group.

        Args:
            limit: Optional maximum number of embeddings to fetch

        Returns:
            List of dicts with keys: id, news_url_id, embedding_vector, created_at
        """
        logger.info("Fetching ungrouped fact embeddings...")

        try:
            embeddings: List[Dict] = []

            for batch in self._iter_ungrouped_embedding_batches(
                limit=limit,
                batch_size=1000,
            ):
                embeddings.extend(batch)

            logger.info(f"Fetched {len(embeddings)} ungrouped fact embeddings")

            return embeddings

        except Exception as e:
            logger.error(f"Error fetching ungrouped embeddings: {e}")
            raise

    def fetch_embeddings_by_news_url_ids(
        self, news_url_ids: List[str]
    ) -> List[Dict]:
        """Fetch fact embeddings for a specific list of news_url IDs."""

        if not news_url_ids:
            return []

        logger.info(
            "Fetching fact embeddings for %s requested news_url_ids",
            len(news_url_ids),
        )

        unique_ids: List[str] = []
        seen = set()
        for news_id in news_url_ids:
            if news_id and news_id not in seen:
                seen.add(news_id)
                unique_ids.append(news_id)

        if not unique_ids:
            return []

        chunk_size = 100
        embeddings: List[Dict] = []

        for start in range(0, len(unique_ids), chunk_size):
            chunk = unique_ids[start : start + chunk_size]
            try:
                response = (
                    self.client.table("news_facts")
                    .select(
                        "id, news_url_id, created_at, facts_embeddings!inner(id, embedding_vector, created_at)"
                    )
                    .in_("news_url_id", chunk)
                    .execute()
                )

                for fact in response.data or []:
                    for embedding in fact.get("facts_embeddings", []) or []:
                        normalized = self._normalize_fact_embedding(
                            {
                                "id": embedding.get("id"),
                                "news_fact_id": fact.get("id"),
                                "embedding_vector": embedding.get("embedding_vector"),
                                "created_at": embedding.get("created_at"),
                                "news_facts": {
                                    "news_url_id": fact.get("news_url_id"),
                                    "created_at": fact.get("created_at"),
                                },
                            }
                        )
                        if normalized:
                            embeddings.append(normalized)

            except Exception as exc:
                logger.error(
                    "Error fetching fact embeddings for IDs %s-%s: %s",
                    start,
                    start + len(chunk) - 1,
                    exc,
                )
                raise

        logger.info(
            "Fetched %s fact embeddings for requested IDs", len(embeddings)
        )

        return embeddings
    

    def fetch_all_embeddings(
        self,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Fetch all fact embeddings regardless of grouping status.
        Only fetches embeddings from the last N days (configured via days_lookback).
        
        Args:
            limit: Optional maximum number of embeddings to fetch
            
        Returns:
            List of dicts with keys: id, news_url_id, news_fact_id, embedding_vector,
            created_at
        """
        logger.info("Fetching all fact embeddings...")
        
        try:
            cutoff_date = self._get_cutoff_date()
            logger.info(
                f"Filtering facts created after {cutoff_date} ({self.days_lookback} days)"
            )
            
            embeddings: List[Dict] = []

            for batch in self._iter_all_embedding_batches(
                limit=limit,
                batch_size=1000,
            ):
                embeddings.extend(batch)

            logger.info(f"Fetched {len(embeddings)} total fact embeddings")

            return embeddings
            
        except Exception as e:
            logger.error(f"Error fetching all embeddings: {e}")
            raise

    def get_embeddings_by_news_url_ids(
        self,
        news_url_ids: List[str]
    ) -> List[Dict]:
        """
        Fetch fact embeddings for specific news URLs.
        
        Args:
            news_url_ids: List of news URL IDs to fetch
            
        Returns:
            List of dicts with keys: id, news_fact_id, news_url_id,
            embedding_vector, created_at
        """
        if not news_url_ids:
            return []

        logger.debug(f"Fetching fact embeddings for {len(news_url_ids)} news URLs")

        try:
            return self.fetch_embeddings_by_news_url_ids(news_url_ids)
        except Exception as e:
            logger.error(f"Error fetching embeddings by news URL IDs: {e}")
            raise

    def get_embedding_stats(self) -> Dict:
        """
        Get statistics about fact embeddings used for grouping.

        Returns:
            Dict with keys: total_embeddings, embeddings_with_vectors,
            grouped_count, ungrouped_count
        """
        logger.info("Fetching embedding statistics...")

        try:
            total_response = self.client.table("facts_embeddings").select(
                "id", count="exact"
            ).execute()
            total_count = total_response.count or 0

            vector_response = self.client.table("facts_embeddings").select(
                "id", count="exact"
            ).not_.is_("embedding_vector", "null").execute()
            vector_count = vector_response.count or 0

            grouped_response = self.client.table("story_group_members").select(
                "news_fact_id", count="exact"
            ).not_.is_("news_fact_id", "null").execute()
            grouped_count = grouped_response.count or 0

            ungrouped_count = vector_count - grouped_count

            stats = {
                "total_embeddings": total_count,
                "embeddings_with_vectors": vector_count,
                "grouped_count": grouped_count,
                "ungrouped_count": max(0, ungrouped_count),
            }
            
            logger.info(f"Embedding stats: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error fetching embedding statistics: {e}")
            raise

    def iter_grouping_embeddings(
        self,
        regroup: bool,
        limit: Optional[int] = None,
        batch_size: int = 200,
    ):
        """Yield story embeddings in batches for grouping workflows."""

        if batch_size <= 0:
            raise ValueError("Batch size must be a positive integer")

        if regroup:
            yield from self._iter_all_embedding_batches(
                limit=limit,
                batch_size=batch_size,
            )
        else:
            yield from self._iter_ungrouped_embedding_batches(
                limit=limit,
                batch_size=batch_size,
            )

    def _iter_ungrouped_embedding_batches(
        self,
        limit: Optional[int],
        batch_size: int,
    ):
        logger.info("Streaming ungrouped fact embeddings from database...")

        page_size = max(batch_size, 500)
        offset = 0
        yielded = 0
        cutoff_date = self._get_cutoff_date()
        grouped_fact_ids = self._get_grouped_fact_ids()

        while True:
            logger.info(
                "Fetching ungrouped fact embeddings at offset %s (page size %s)...",
                offset,
                page_size,
            )

            response = (
                self.client.table("facts_embeddings")
                .select(
                    "id, news_fact_id, embedding_vector, created_at, news_facts!inner(news_url_id, created_at)"
                )
                .gte("created_at", cutoff_date)
                .order("created_at", desc=True)
                .range(offset, offset + page_size - 1)
                .execute()
            )

            if not response.data:
                break

            parsed_batch = []
            for record in response.data:
                if record.get("news_fact_id") in grouped_fact_ids:
                    continue

                normalized = self._normalize_fact_embedding(record)
                if normalized:
                    parsed_batch.append(normalized)

            batch_index = 0
            while batch_index < len(parsed_batch):
                if limit is not None and yielded >= limit:
                    return

                remaining = limit - yielded if limit is not None else batch_size
                current_size = min(batch_size, remaining)
                chunk = parsed_batch[batch_index: batch_index + current_size]

                if not chunk:
                    break

                yield chunk
                yielded += len(chunk)
                batch_index += current_size

            if limit is not None and yielded >= limit:
                return

            if len(response.data) < page_size:
                break

            offset += page_size

        logger.info(f"Yielded {yielded} ungrouped fact embeddings")

    def _iter_all_embedding_batches(
        self,
        limit: Optional[int],
        batch_size: int,
    ):
        logger.info("Streaming all fact embeddings from database...")

        cutoff_date = self._get_cutoff_date()
        page_size = max(batch_size, 500)
        offset = 0
        yielded = 0

        while True:
            response = (
                self.client.table("facts_embeddings")
                .select(
                    "id, news_fact_id, embedding_vector, created_at, news_facts!inner(news_url_id, created_at)"
                )
                .gte("created_at", cutoff_date)
                .order("created_at", desc=False)
                .range(offset, offset + page_size - 1)
                .execute()
            )

            if not response.data:
                break

            parsed_batch = []
            for record in response.data:
                normalized = self._normalize_fact_embedding(record)
                if normalized:
                    parsed_batch.append(normalized)

            batch_index = 0
            while batch_index < len(parsed_batch):
                if limit is not None and yielded >= limit:
                    return

                remaining = limit - yielded if limit is not None else batch_size
                current_size = min(batch_size, remaining)
                chunk = parsed_batch[batch_index: batch_index + current_size]

                if not chunk:
                    break

                yield chunk
                yielded += len(chunk)
                batch_index += current_size

            if limit is not None and yielded >= limit:
                return

            if len(response.data) < page_size:
                break

            offset += page_size

        logger.info(f"Yielded {yielded} total fact embeddings")
