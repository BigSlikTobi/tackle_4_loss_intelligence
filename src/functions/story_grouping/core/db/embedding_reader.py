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

    def __init__(
        self, 
        days_lookback: int = 14,
        table_name: str = "facts_embeddings",
        id_column: str = "id",
        vector_column: str = "embedding_vector",
        grouping_key_column: str = "news_url_id",
        # Optional: legacy join configuration (if we are using the standard schema)
        is_legacy_schema: bool = True,
        # Optional: Postgres schema (default: public)
        schema_name: str = "public"
    ):
        """
        Initialize the embedding reader.
        
        Args:
            days_lookback: Number of days to look back for stories (default: 14)
            table_name: Name of the table to read embeddings from
            id_column: Name of the ID column (primary key of embedding table)
            vector_column: Name of the vector column
            grouping_key_column: Name of the column used for grouping (e.g. news_url_id or news_url)
            is_legacy_schema: If True, assumes the standard schema with joins (facts_embeddings -> news_facts).
                              If False, treats table_name as a flat table containing all info.
        """
        self.client = get_supabase_client()
        self.days_lookback = days_lookback
        self.table_name = table_name
        self.id_column = id_column
        self.vector_column = vector_column
        self.grouping_key_column = grouping_key_column
        self.is_legacy_schema = is_legacy_schema
        self.schema_name = schema_name
    
    def _table(self, table_name: str):
        """Helper to get table object with correct schema."""
        return self.client.schema(self.schema_name).table(table_name)
    
    def _get_cutoff_date(self) -> str:
        """
        Get the cutoff date for filtering stories.
        
        Returns:
            ISO format datetime string for the cutoff date
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_lookback)
        return cutoff.isoformat()

    def _normalize_embedding_record(self, record: Dict) -> Optional[Dict]:
        """
        Normalize a raw DB record into a standard dict for the pipeline.
        Handles both legacy joined format and flat table format.
        """
        vector = parse_vector(record.get(self.vector_column))
        
        if self.is_legacy_schema:
            # Legacy logic: record is from facts_embeddings, with news_facts joined
            news_fact = record.get("news_facts") or {}
            grouping_key = news_fact.get(self.grouping_key_column)
            created_at = news_fact.get("created_at") or record.get("created_at")
            fact_id = record.get("news_fact_id")
        else:
            # Flat table logic
            grouping_key = record.get(self.grouping_key_column)
            created_at = record.get("created_at")
            # For flat tables, fact_id might be the same as id or another column
            # If not present, we can default to None or use ID
            fact_id = record.get("news_fact_id")

        if vector is None or grouping_key is None:
            return None

        return {
            "id": record.get(self.id_column),
            "news_fact_id": fact_id,
            "news_url_id": grouping_key, # We standardise on 'news_url_id' even if the key is a URL string
            "embedding_vector": vector,
            "created_at": created_at,
            "metadata": record,
        }

    def _get_grouped_key_ids(self) -> set:
        """Collect grouping keys (e.g. news_url_ids) that are already assigned to story groups."""
        # Note: This logic assumes 'story_group_members' table always uses 'news_url_id' as the key.
        # If the user provides a custom memberships table, this might need an update in the future.
        # For now, we assume the memberships table structure is fixed.

        grouped_keys: set = set()
        page_size = 1000
        offset = 0
        max_batches = 15
        batches = 0

        while batches < max_batches:
            response = (
                self._table("story_group_members")
                .select("news_url_id")
                .not_.is_("news_url_id", "null")
                .range(offset, offset + page_size - 1)
                .execute()
            )

            if not response.data:
                break

            grouped_keys.update(
                item.get("news_url_id") for item in response.data if item.get("news_url_id")
            )

            if len(response.data) < page_size:
                break

            offset += page_size
            batches += 1

        logger.info("Found %s already grouped keys", len(grouped_keys))
        return grouped_keys

    def fetch_ungrouped_embeddings(
        self,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Fetch embeddings for stories not yet assigned to a group.

        Args:
            limit: Optional maximum number of embeddings to fetch

        Returns:
            List of dicts with keys: id, news_url_id, embedding_vector, created_at
        """
        logger.info(f"Fetching ungrouped embeddings from {self.table_name}...")

        try:
            embeddings: List[Dict] = []

            for batch in self._iter_ungrouped_embedding_batches(
                limit=limit,
                batch_size=1000,
            ):
                embeddings.extend(batch)

            logger.info(f"Fetched {len(embeddings)} ungrouped embeddings")

            return embeddings

        except Exception as e:
            logger.error(f"Error fetching ungrouped embeddings: {e}")
            raise

    def fetch_embedding_by_id(self, id_value: str) -> Optional[Dict]:
        """
        Fetch a single embedding by its primary ID column.
        Useful when the input story_id is a UUID but we group by another column (e.g. URL).
        """
        logger.info(f"Fetching embedding by ID {id_value} from {self.table_name}...")
        
        try:
            query = self._table(self.table_name)
            
            if self.is_legacy_schema:
                # Legacy join query
                response = (
                    query
                    .select(
                        f"{self.id_column}, news_fact_id, {self.vector_column}, created_at, news_facts!inner({self.grouping_key_column}, created_at)"
                    )
                    .eq(self.id_column, id_value)
                    .execute()
                )
            else:
                # Flat table query
                response = (
                    query
                    .select("*")
                    .eq(self.id_column, id_value)
                    .execute()
                )
            
            if response.data:
                return self._normalize_embedding_record(response.data[0])
            
            return None
            
        except Exception as e:
            # Catch type mismatch errors (e.g. searching UUID column with URL string, or BigInt with UUID)
            error_str = str(e).lower()
            if "invalid input syntax" in error_str:
                logger.warning(f"Type mismatch fetching embedding by ID {id_value}: {e}")
                return None
            
            logger.error(f"Error fetching embedding by ID {id_value}: {e}")
            raise

    def fetch_embeddings_by_keys(
        self, keys: List[str]
    ) -> List[Dict]:
        """Fetch embeddings for a specific list of grouping keys (e.g. news_url_ids)."""

        if not keys:
            return []

        logger.info(
            "Fetching embeddings for %s requested keys from %s",
            len(keys),
            self.table_name
        )

        unique_keys: List[str] = list(set(k for k in keys if k))
        if not unique_keys:
            return []

        chunk_size = 100
        embeddings: List[Dict] = []

        for start in range(0, len(unique_keys), chunk_size):
            chunk = unique_keys[start : start + chunk_size]
            try:
                query = self._table(self.table_name)
                
                if self.is_legacy_schema:
                    # Legacy join query
                    response = (
                        query
                        .select(
                            f"{self.id_column}, news_fact_id, {self.vector_column}, created_at, news_facts!inner({self.grouping_key_column}, created_at)"
                        )
                        .in_(f"news_facts.{self.grouping_key_column}", chunk)
                        .execute()
                    )
                else:
                    # Flat table query
                    response = (
                        query
                        .select("*")
                        .in_(self.grouping_key_column, chunk)
                        .execute()
                    )

                for record in response.data or []:
                    normalized = self._normalize_embedding_record(record)
                    if normalized:
                        embeddings.append(normalized)

            except Exception as exc:
                # Catch type mismatch errors (e.g. searching UUID column with URL string)
                # This allows fallback logic in main.py to handle it (e.g. try searching by ID instead)
                error_str = str(exc).lower()
                if "invalid input syntax" in error_str:
                    logger.warning(
                        "Type mismatch fetching keys %s-%s: %s. Returning empty to allow fallback.",
                        start,
                        start + len(chunk) - 1,
                        exc
                    )
                    # If the entire chunk fails due to type error, we skip it
                    continue

                logger.error(
                    "Error fetching embeddings for keys %s-%s: %s",
                    start,
                    start + len(chunk) - 1,
                    exc,
                )
                raise

        logger.info(
            "Fetched %s embeddings for requested keys", len(embeddings)
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
        logger.info(f"Fetching all embeddings from {self.table_name}...")
        
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

            logger.info(f"Fetched {len(embeddings)} total embeddings")

            return embeddings
            
        except Exception as e:
            logger.error(f"Error fetching all embeddings: {e}")
            raise

    # Alias for backward compatibility (if needed by other modules, though we updated pipeline)
    def fetch_embeddings_by_news_url_ids(self, news_url_ids: List[str]) -> List[Dict]:
        return self.fetch_embeddings_by_keys(news_url_ids)

    def get_embedding_stats(self) -> Dict:
        """
        Get statistics about embeddings used for grouping.

        Returns:
            Dict with keys: total_embeddings, embeddings_with_vectors,
            grouped_count, ungrouped_count
        """
        logger.info(f"Fetching embedding statistics from {self.table_name}...")

        try:
            total_response = self._table(self.table_name).select(
                self.id_column, count="exact"
            ).execute()
            total_count = total_response.count or 0

            vector_response = self._table(self.table_name).select(
                self.id_column, count="exact"
            ).not_.is_(self.vector_column, "null").execute()
            vector_count = vector_response.count or 0

            grouped_response = self._table("story_group_members").select(
                "id", count="exact"
            ).execute()
            grouped_count = grouped_response.count or 0

            # Approximation for ungrouped count since we can't easily join count across tables efficiently here
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
        logger.info(f"Streaming ungrouped embeddings from {self.table_name}...")

        page_size = max(batch_size, 500)
        offset = 0
        yielded = 0
        cutoff_date = self._get_cutoff_date()
        grouped_keys = self._get_grouped_key_ids() # Keys already in groups

        while True:
            logger.info(
                "Fetching ungrouped embeddings at offset %s (page size %s)...",
                offset,
                page_size,
            )

            query = self.client.table(self.table_name)
            
            if self.is_legacy_schema:
                # Legacy join query
                response = (
                    query
                    .select(
                        f"{self.id_column}, news_fact_id, {self.vector_column}, created_at, news_facts!inner({self.grouping_key_column}, created_at)"
                    )
                    .gte("created_at", cutoff_date)
                    .order("created_at", desc=True)
                    .range(offset, offset + page_size - 1)
                    .execute()
                )
            else:
                # Flat table query
                response = (
                    query
                    .select("*")
                    .gte("created_at", cutoff_date)
                    .order("created_at", desc=True)
                    .range(offset, offset + page_size - 1)
                    .execute()
                )

            if not response.data:
                break

            parsed_batch = []
            for record in response.data:
                normalized = self._normalize_embedding_record(record)
                if not normalized:
                    continue
                    
                # Skip if already grouped
                # Note: This is an in-memory check which is fine for reasonable dataset sizes,
                # but might need DB-side filtering (NOT IN) for huge datasets.
                if normalized["news_url_id"] in grouped_keys:
                    continue

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

        logger.info(f"Yielded {yielded} ungrouped embeddings")

    def _iter_all_embedding_batches(
        self,
        limit: Optional[int],
        batch_size: int,
    ):
        logger.info(f"Streaming all embeddings from {self.table_name}...")

        cutoff_date = self._get_cutoff_date()
        page_size = max(batch_size, 500)
        offset = 0
        yielded = 0

        while True:
            query = self.client.table(self.table_name)
            
            if self.is_legacy_schema:
                response = (
                    query
                    .select(
                         f"{self.id_column}, news_fact_id, {self.vector_column}, created_at, news_facts!inner({self.grouping_key_column}, created_at)"
                    )
                    .gte("created_at", cutoff_date)
                    .order("created_at", desc=False)
                    .range(offset, offset + page_size - 1)
                    .execute()
                )
            else:
                response = (
                    query
                    .select("*")
                    .gte("created_at", cutoff_date)
                    .order("created_at", desc=False)
                    .range(offset, offset + page_size - 1)
                    .execute()
                )

            if not response.data:
                break

            parsed_batch = []
            for record in response.data:
                normalized = self._normalize_embedding_record(record)
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

        logger.info(f"Yielded {yielded} total embeddings")
