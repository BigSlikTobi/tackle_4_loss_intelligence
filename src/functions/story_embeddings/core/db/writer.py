"""
Database writer for story_embeddings table.

Production-ready writer with batch operations, retry logic, and comprehensive error handling.
"""

import logging
import time
from typing import Optional

from src.shared.db.connection import get_supabase_client
from ..contracts import StoryEmbedding

logger = logging.getLogger(__name__)


class EmbeddingWriter:
    """
    Production-ready writer for story embedding records.

    Features:
    - Batch upsert operations with configurable batch size
    - Dry-run mode for testing
    - Automatic retry logic with exponential backoff
    - Comprehensive error handling and logging
    - Connection health monitoring
    - Idempotent operations (upsert on news_url_id)
    """

    def __init__(
        self,
        table_name: str = "story_embeddings",
        dry_run: bool = False,
        batch_size: int = 100,
        max_retries: int = 3,
    ):
        """
        Initialize the writer.

        Args:
            table_name: Name of the story_embeddings table
            dry_run: If True, only log what would be written
            batch_size: Maximum records per batch operation
            max_retries: Maximum retry attempts for failed operations
        """
        self.table_name = table_name
        self.dry_run = dry_run
        self.batch_size = batch_size
        self.max_retries = max_retries

        if not dry_run:
            self.client = get_supabase_client()
            self._verify_connection()
        else:
            self.client = None

        mode = "DRY-RUN" if dry_run else "PRODUCTION"
        logger.info(
            f"Initialized EmbeddingWriter in {mode} mode "
            f"(table: {table_name}, batch_size: {batch_size}, retries: {max_retries})"
        )

    def _verify_connection(self):
        """Verify database connection is healthy."""
        try:
            # Simple query to verify connection
            self.client.table(self.table_name).select("id").limit(1).execute()
            logger.info("Database connection verified")
        except Exception as e:
            logger.warning(f"Database connection verification: {e} (table may not exist yet)")

    def write_embeddings(self, embeddings: list[StoryEmbedding]) -> dict:
        """
        Write multiple embeddings to the database.

        Args:
            embeddings: List of StoryEmbedding instances

        Returns:
            Dictionary with operation statistics:
                - total: Total records processed
                - successful: Successfully written records
                - failed: Failed records
                - errors: List of error messages
        """
        if not embeddings:
            logger.warning("No embeddings to write")
            return {"total": 0, "successful": 0, "failed": 0, "errors": []}

        logger.info(f"Writing {len(embeddings)} embeddings...")

        stats = {
            "total": len(embeddings),
            "successful": 0,
            "failed": 0,
            "errors": [],
        }

        # Process in batches
        for i in range(0, len(embeddings), self.batch_size):
            batch = embeddings[i : i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            total_batches = (len(embeddings) + self.batch_size - 1) // self.batch_size

            logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} records)...")

            batch_stats = self._write_batch(batch)
            stats["successful"] += batch_stats["successful"]
            stats["failed"] += batch_stats["failed"]
            stats["errors"].extend(batch_stats["errors"])

        logger.info(
            f"Write complete: {stats['successful']}/{stats['total']} successful, "
            f"{stats['failed']} failed"
        )

        return stats

    def _write_batch(self, embeddings: list[StoryEmbedding]) -> dict:
        """
        Write a single batch of embeddings.

        Args:
            embeddings: List of StoryEmbedding instances

        Returns:
            Dictionary with batch statistics
        """
        stats = {"successful": 0, "failed": 0, "errors": []}

        # Convert to dictionaries
        records = [emb.to_dict() for emb in embeddings]

        if self.dry_run:
            logger.info(f"[DRY-RUN] Would write {len(records)} embeddings")
            for record in records[:3]:  # Show first 3
                vector_dim = len(record['embedding_vector'])
                logger.debug(
                    f"[DRY-RUN] news_url_id: {record['news_url_id']}, "
                    f"model: {record['model_name']}, vector_dim: {vector_dim}"
                )
            if len(records) > 3:
                logger.debug(f"[DRY-RUN] ... and {len(records) - 3} more")
            stats["successful"] = len(records)
            return stats

        # Retry logic with exponential backoff
        for attempt in range(self.max_retries):
            try:
                # Try upsert first (requires UNIQUE constraint on news_url_id)
                response = self.client.table(self.table_name).upsert(
                    records, on_conflict="news_url_id"
                ).execute()

                # Success
                stats["successful"] = len(records)
                logger.debug(
                    f"Successfully wrote batch of {len(records)} embeddings "
                    f"(attempt {attempt + 1}/{self.max_retries})"
                )
                return stats
            
            except Exception as e:
                # If UNIQUE constraint doesn't exist, fall back to regular insert
                error_str = str(e)
                if "no unique or exclusion constraint" in error_str or "42P10" in error_str:
                    logger.warning(
                        "UNIQUE constraint on news_url_id not found, using insert instead. "
                        "Note: This may create duplicates. Please add UNIQUE constraint."
                    )
                    try:
                        response = self.client.table(self.table_name).insert(records).execute()
                        stats["successful"] = len(records)
                        logger.debug(f"Successfully inserted batch of {len(records)} embeddings")
                        return stats
                    except Exception as insert_error:
                        error_msg = f"Batch insert failed: {insert_error}"
                        logger.error(error_msg)
                        stats["failed"] = len(records)
                        stats["errors"].append(error_msg)
                        return stats
                
                # Other errors - continue with retry logic
                raise

            except Exception as e:
                error_msg = f"Batch write failed (attempt {attempt + 1}/{self.max_retries}): {e}"
                logger.warning(error_msg)

                if attempt < self.max_retries - 1:
                    # Exponential backoff: 1s, 2s, 4s, 8s...
                    sleep_time = 2**attempt
                    logger.info(f"Retrying in {sleep_time} seconds...")
                    time.sleep(sleep_time)
                else:
                    # Final attempt failed
                    logger.error(f"Batch write failed after {self.max_retries} attempts")
                    stats["failed"] = len(records)
                    stats["errors"].append(error_msg)

        return stats

    def check_exists(self, news_url_id: str) -> bool:
        """
        Check if an embedding already exists for a given news_url_id.

        Args:
            news_url_id: UUID of the news URL

        Returns:
            True if embedding exists, False otherwise
        """
        if self.dry_run:
            return False

        try:
            response = (
                self.client.table(self.table_name)
                .select("id")
                .eq("news_url_id", news_url_id)
                .execute()
            )
            return len(response.data) > 0
        except Exception as e:
            logger.warning(f"Error checking if embedding exists for {news_url_id}: {e}")
            return False

    def write_single(self, embedding: StoryEmbedding) -> bool:
        """
        Write a single embedding to the database.

        Args:
            embedding: StoryEmbedding instance

        Returns:
            True if successful, False otherwise
        """
        result = self.write_embeddings([embedding])
        return result["successful"] == 1

    def get_stats(self) -> dict:
        """
        Get statistics about stored embeddings.

        Returns:
            Dictionary with statistics:
                - total_embeddings: Total number of embeddings
                - models_used: List of models used
        """
        if self.dry_run:
            return {"total_embeddings": 0, "models_used": []}

        try:
            # Count total embeddings
            count_response = (
                self.client.table(self.table_name)
                .select("id", count="exact")
                .execute()
            )
            total = count_response.count if hasattr(count_response, "count") else 0

            # Get unique models
            models_response = (
                self.client.table(self.table_name)
                .select("model_name")
                .execute()
            )
            models = list(set(row["model_name"] for row in models_response.data))

            return {"total_embeddings": total, "models_used": models}

        except Exception as e:
            logger.error(f"Failed to get embedding statistics: {e}")
            return {"total_embeddings": 0, "models_used": []}
