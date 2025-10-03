"""
Database writer for context_summaries table.

Production-ready writer with batch operations, retry logic, and comprehensive error handling.
"""

import logging
from typing import Optional
import time

from src.shared.db.connection import get_supabase_client
from ..contracts import ContentSummary

logger = logging.getLogger(__name__)


class SummaryWriter:
    """
    Production-ready writer for content summary records.

    Features:
    - Batch upsert operations with configurable batch size
    - Dry-run mode for testing
    - Automatic retry logic with exponential backoff
    - Comprehensive error handling and logging
    - Connection health monitoring
    - Idempotent operations (upsert)
    """

    def __init__(
        self,
        table_name: str = "context_summaries",
        dry_run: bool = False,
        batch_size: int = 100,
        max_retries: int = 3,
    ):
        """
        Initialize the writer.

        Args:
            table_name: Name of the context_summaries table
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
            f"Initialized SummaryWriter in {mode} mode "
            f"(table: {table_name}, batch_size: {batch_size}, retries: {max_retries})"
        )
    
    def _verify_connection(self):
        """Verify database connection is healthy."""
        try:
            # Simple query to verify connection
            self.client.table(self.table_name).select("id").limit(1).execute()
            logger.info("Database connection verified")
        except Exception as e:
            logger.error(f"Database connection verification failed: {e}")
            raise Exception(f"Failed to connect to database: {e}") from e

    def write_summaries(self, summaries: list[ContentSummary]) -> dict:
        """
        Write multiple summaries to the database.

        Args:
            summaries: List of ContentSummary instances

        Returns:
            Dictionary with operation statistics:
                - total: Total records processed
                - successful: Successfully written records
                - failed: Failed records
                - errors: List of error messages
        """
        if not summaries:
            logger.warning("No summaries to write")
            return {"total": 0, "successful": 0, "failed": 0, "errors": []}

        logger.info(f"Writing {len(summaries)} summaries...")

        stats = {
            "total": len(summaries),
            "successful": 0,
            "failed": 0,
            "errors": [],
        }

        # Process in batches
        for i in range(0, len(summaries), self.batch_size):
            batch = summaries[i : i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            total_batches = (len(summaries) + self.batch_size - 1) // self.batch_size

            logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} records)...")

            if self.dry_run:
                self._log_dry_run_batch(batch)
                stats["successful"] += len(batch)
            else:
                batch_stats = self._write_batch_with_retry(batch)
                stats["successful"] += batch_stats["successful"]
                stats["failed"] += batch_stats["failed"]
                stats["errors"].extend(batch_stats["errors"])

        logger.info(f"Write complete: {stats['successful']} successful, {stats['failed']} failed")
        return stats
    
    def _write_batch_with_retry(self, batch: list[ContentSummary]) -> dict:
        """
        Write a batch with exponential backoff retry logic.
        
        Args:
            batch: List of ContentSummary instances
            
        Returns:
            Batch statistics dictionary
        """
        last_exception = None
        
        for attempt in range(1, self.max_retries + 1):
            try:
                return self._write_batch(batch)
                
            except Exception as e:
                last_exception = e
                logger.warning(f"Batch write attempt {attempt}/{self.max_retries} failed: {e}")
                
                if attempt < self.max_retries:
                    # Exponential backoff
                    wait_time = 2 ** attempt
                    logger.info(f"Retrying batch in {wait_time}s...")
                    time.sleep(wait_time)
        
        # All retries failed
        logger.error(f"All {self.max_retries} attempts failed for batch")
        return {
            "successful": 0,
            "failed": len(batch),
            "errors": [f"Batch write failed after {self.max_retries} attempts: {last_exception}"],
        }

    def _write_batch(self, batch: list[ContentSummary]) -> dict:
        """
        Write a single batch of summaries.

        Args:
            batch: List of ContentSummary instances

        Returns:
            Batch statistics
        """
        stats = {"successful": 0, "failed": 0, "errors": []}

        try:
            # Convert to dictionaries
            records = [summary.to_dict() for summary in batch]

            # Upsert to database (upsert on news_url_id to handle re-summarization)
            response = (
                self.client.table(self.table_name)
                .upsert(records, on_conflict="news_url_id")
                .execute()
            )

            stats["successful"] = len(response.data)
            logger.info(f"Successfully wrote {stats['successful']} summaries")

        except Exception as e:
            error_msg = f"Batch write failed: {e}"
            logger.error(error_msg, exc_info=True)
            stats["failed"] = len(batch)
            stats["errors"].append(error_msg)

        return stats

    def _log_dry_run_batch(self, batch: list[ContentSummary]) -> None:
        """
        Log batch details in dry-run mode.

        Args:
            batch: List of ContentSummary instances
        """
        logger.info(f"[DRY-RUN] Would write {len(batch)} summaries:")
        for summary in batch[:3]:  # Show first 3 as examples
            logger.info(f"  - URL ID: {summary.news_url_id}")
            logger.info(f"    Summary: {summary.summary[:100]}...")
            logger.info(f"    Players: {summary.players_mentioned}")
            logger.info(f"    Teams: {summary.teams_mentioned}")
            logger.info(f"    Type: {summary.article_type}, Sentiment: {summary.sentiment}")
            logger.info(f"    Model: {summary.model_used}, Fallback: {summary.url_retrieval_status}")

        if len(batch) > 3:
            logger.info(f"  ... and {len(batch) - 3} more")

    def write_single(self, summary: ContentSummary) -> bool:
        """
        Write a single summary (convenience method).

        Args:
            summary: ContentSummary instance

        Returns:
            True if successful, False otherwise
        """
        result = self.write_summaries([summary])
        return result["successful"] == 1

    def check_exists(self, news_url_id: str) -> bool:
        """
        Check if a summary already exists for a URL.

        Args:
            news_url_id: UUID of the news_url record

        Returns:
            True if summary exists, False otherwise
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would check if summary exists for URL ID: {news_url_id}")
            return False

        try:
            response = (
                self.client.table(self.table_name)
                .select("news_url_id")
                .eq("news_url_id", news_url_id)
                .limit(1)
                .execute()
            )

            exists = len(response.data) > 0
            logger.debug(f"Summary exists for URL ID {news_url_id}: {exists}")
            return exists

        except Exception as e:
            logger.error(f"Failed to check if summary exists: {e}", exc_info=True)
            return False
