"""
Database writer for news_urls table.

Handles upserting news URL records to Supabase with conflict resolution.
Optimized for production with batch processing and comprehensive error handling.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
import logging

from src.shared.db.connection import get_supabase_client

logger = logging.getLogger(__name__)

# Database operation constants
DEFAULT_BATCH_SIZE = 100
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 1


class NewsUrlWriter:
    """
    Production-ready writer for news URL records to the news_urls table.

    Handles batch upserts with conflict resolution, retry logic, and comprehensive monitoring.
    """

    def __init__(
        self, 
        table_name: str = "news_urls", 
        conflict_column: str = "url",
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_retries: int = MAX_RETRIES,
    ):
        """
        Initialize database writer.

        Args:
            table_name: Name of the Supabase table
            conflict_column: Column to use for conflict resolution (upsert)
            batch_size: Number of records to process in each batch
            max_retries: Maximum retry attempts for failed operations
        """
        self.table_name = table_name
        self.conflict_column = conflict_column
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.client = get_supabase_client()

    def write(self, records: List[Dict[str, Any]], dry_run: bool = False) -> Dict[str, Any]:
        """
        Write records to the database with batch processing and retry logic.

        Args:
            records: List of record dictionaries to insert
            dry_run: If True, simulate write without actually inserting

        Returns:
            Dictionary with write statistics and performance metrics
        """
        if dry_run:
            logger.info(f"[DRY RUN] Would upsert {len(records)} records to {self.table_name}")
            return {
                "success": True,
                "dry_run": True,
                "records_written": len(records),
                "records": records,
            }

        if not records:
            logger.info("No records to write")
            return {"success": True, "records_written": 0}

        start_time = time.time()
        logger.info(f"Starting batch upsert of {len(records)} records to {self.table_name}")

        # Process records in batches
        total_written = 0
        failed_batches = 0
        batch_count = (len(records) + self.batch_size - 1) // self.batch_size

        for i in range(0, len(records), self.batch_size):
            batch = records[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            
            logger.debug(f"Processing batch {batch_num}/{batch_count} ({len(batch)} records)")
            
            batch_result = self._write_batch_with_retry(batch)
            
            if batch_result["success"]:
                total_written += batch_result["records_written"]
            else:
                failed_batches += 1
                logger.error(f"Batch {batch_num} failed: {batch_result.get('error', 'Unknown error')}")

        write_time = time.time() - start_time
        success_rate = ((batch_count - failed_batches) / batch_count) * 100 if batch_count > 0 else 0

        result = {
            "success": failed_batches == 0,
            "records_written": total_written,
            "total_records": len(records),
            "batches_processed": batch_count,
            "failed_batches": failed_batches,
            "success_rate_percent": success_rate,
            "write_time_seconds": write_time,
            "records_per_second": total_written / write_time if write_time > 0 else 0,
        }

        if failed_batches > 0:
            result["error"] = f"{failed_batches}/{batch_count} batches failed"

        logger.info(
            f"Write complete: {total_written}/{len(records)} records written "
            f"in {write_time:.2f}s ({result['records_per_second']:.1f} rec/s)"
        )

        return result

    def _write_batch_with_retry(self, batch: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Write a single batch with retry logic.

        Args:
            batch: List of records to write

        Returns:
            Dictionary with batch write result
        """
        last_error = None
        
        for attempt in range(self.max_retries + 1):
            try:
                response = (
                    self.client.table(self.table_name)
                    .upsert(batch, on_conflict=self.conflict_column)
                    .execute()
                )

                return {
                    "success": True,
                    "records_written": len(batch),
                    "attempt": attempt + 1,
                }

            except Exception as e:
                last_error = e
                logger.warning(f"Batch write attempt {attempt + 1} failed: {e}")
                
                if attempt < self.max_retries:
                    delay = RETRY_DELAY_SECONDS * (2 ** attempt)  # Exponential backoff
                    logger.debug(f"Retrying in {delay}s...")
                    time.sleep(delay)

        return {
            "success": False,
            "error": str(last_error),
            "records_written": 0,
            "attempts": self.max_retries + 1,
        }

    def clear(self, filter_column: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
        """
        Clear records from the table.

        Args:
            filter_column: Optional column to filter deletion (e.g., only clear specific publisher)
            dry_run: If True, simulate clear without actually deleting

        Returns:
            Dictionary with clear statistics
        """
        if dry_run:
            logger.info(f"[DRY RUN] Would clear records from {self.table_name}")
            return {"success": True, "dry_run": True}

        logger.warning(f"Clearing records from {self.table_name}")

        try:
            # Delete all records (or filtered subset)
            query = self.client.table(self.table_name).delete()

            # Note: Supabase requires a filter for delete operations
            # To delete all, we use a condition that's always true
            if filter_column:
                query = query.neq(filter_column, "")
            else:
                query = query.neq(self.conflict_column, "")

            response = query.execute()

            logger.info(f"Successfully cleared records from {self.table_name}")

            return {
                "success": True,
                "response": response,
            }

        except Exception as e:
            logger.error(f"Error clearing {self.table_name}: {e}")
            return {
                "success": False,
                "error": str(e),
            }
