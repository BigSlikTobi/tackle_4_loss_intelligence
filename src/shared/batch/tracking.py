"""Batch job tracking for content pipeline orchestration.

This module provides functions to track OpenAI Batch API jobs in Supabase,
enabling GitHub Actions workflows to:
- Register new batches after creation
- Poll for pending/completed batches
- Update status as batches complete and are processed
- Handle auto-retry on failure

Usage:
    from src.shared.batch.tracking import BatchTracker
    
    tracker = BatchTracker()
    
    # Register a new batch
    tracker.register_batch(
        batch_id="batch_abc123",
        stage="facts",
        article_count=500,
        model="gpt-5-nano",
    )
    
    # Get pending batches to check
    pending = tracker.get_pending_batches()
    
    # Mark as completed when OpenAI finishes
    tracker.mark_completed(batch_id, output_file_id="file-xyz")
    
    # Mark as processed after writing to DB
    tracker.mark_processed(batch_id, items_processed=450, items_skipped=50)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from ..db import get_supabase_client

logger = logging.getLogger(__name__)


class BatchStage(str, Enum):
    """Pipeline stages that use batch processing."""
    FACTS = "facts"
    KNOWLEDGE = "knowledge"
    SUMMARY = "summary"


class BatchStatus(str, Enum):
    """Batch job status values."""
    CREATING = "creating"        # Batch creation in progress (prevents concurrent creation)
    PENDING = "pending"          # Submitted to OpenAI, awaiting completion
    COMPLETED = "completed"      # OpenAI batch finished, ready to process
    PROCESSING = "processing"    # Currently being processed
    PROCESSED = "processed"      # Successfully processed and written to DB
    FAILED = "failed"            # Processing failed (may auto-retry)
    CANCELLED = "cancelled"      # Manually cancelled


# Stage ordering for pipeline chaining
STAGE_ORDER = [BatchStage.FACTS, BatchStage.KNOWLEDGE, BatchStage.SUMMARY]


def get_next_stage(current_stage: BatchStage) -> Optional[BatchStage]:
    """Get the next stage in the pipeline after the current one.
    
    Args:
        current_stage: The current pipeline stage
        
    Returns:
        The next stage, or None if at the final stage
    """
    try:
        current_idx = STAGE_ORDER.index(current_stage)
        if current_idx < len(STAGE_ORDER) - 1:
            return STAGE_ORDER[current_idx + 1]
    except ValueError:
        pass
    return None


@dataclass
class BatchJob:
    """Represents a batch job record from the database."""
    id: str
    batch_id: str
    stage: BatchStage
    status: BatchStatus
    article_count: int
    request_count: int
    model: Optional[str]
    input_file_id: Optional[str]
    output_file_id: Optional[str]
    created_at: datetime
    submitted_at: Optional[datetime]
    completed_at: Optional[datetime]
    processed_at: Optional[datetime]
    retry_count: int
    max_retries: int
    error_message: Optional[str]
    items_processed: Optional[int]
    items_skipped: Optional[int]
    items_failed: Optional[int]
    metadata: Dict[str, Any]
    
    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "BatchJob":
        """Create BatchJob from database row."""
        return cls(
            id=row["id"],
            batch_id=row["batch_id"],
            stage=BatchStage(row["stage"]),
            status=BatchStatus(row["status"]),
            article_count=row.get("article_count", 0),
            request_count=row.get("request_count", 0),
            model=row.get("model"),
            input_file_id=row.get("input_file_id"),
            output_file_id=row.get("output_file_id"),
            created_at=_parse_timestamp(row.get("created_at")),
            submitted_at=_parse_timestamp(row.get("submitted_at")),
            completed_at=_parse_timestamp(row.get("completed_at")),
            processed_at=_parse_timestamp(row.get("processed_at")),
            retry_count=row.get("retry_count", 0),
            max_retries=row.get("max_retries", 1),
            error_message=row.get("error_message"),
            items_processed=row.get("items_processed"),
            items_skipped=row.get("items_skipped"),
            items_failed=row.get("items_failed"),
            metadata=row.get("metadata") or {},
        )


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse timestamp from database value."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # Handle ISO format with or without timezone
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _now_iso() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


class BatchTracker:
    """Track and manage batch jobs in Supabase.
    
    This class provides methods to register, query, and update batch jobs
    for the content processing pipeline.
    """
    
    TABLE_NAME = "batch_jobs"
    
    def __init__(self, client=None):
        """Initialize tracker with Supabase client.
        
        Args:
            client: Optional Supabase client. If None, creates from environment.
        """
        self._client = client
    
    @property
    def client(self):
        """Lazy-load Supabase client."""
        if self._client is None:
            self._client = get_supabase_client()
        return self._client
    
    def register_batch(
        self,
        batch_id: str,
        stage: BatchStage | str,
        *,
        article_count: int = 0,
        request_count: int = 0,
        model: Optional[str] = None,
        input_file_id: Optional[str] = None,
        max_retries: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BatchJob:
        """Register a new batch job after creation.
        
        Args:
            batch_id: OpenAI batch ID (e.g., batch_abc123)
            stage: Pipeline stage (facts, knowledge, summary)
            article_count: Number of articles in the batch
            request_count: Number of API requests in the batch
            model: Model used for processing
            input_file_id: OpenAI input file ID
            max_retries: Maximum retry attempts on failure
            metadata: Additional metadata to store
            
        Returns:
            Created BatchJob record
            
        Raises:
            Exception: If insert fails
        """
        if isinstance(stage, str):
            stage = BatchStage(stage)
        
        now = _now_iso()
        record = {
            "batch_id": batch_id,
            "stage": stage.value,
            "status": BatchStatus.PENDING.value,
            "article_count": article_count,
            "request_count": request_count,
            "model": model,
            "input_file_id": input_file_id,
            "submitted_at": now,
            "max_retries": max_retries,
            "metadata": metadata or {},
        }
        
        response = self.client.table(self.TABLE_NAME).insert(record).execute()
        
        if not response.data:
            raise Exception(f"Failed to register batch {batch_id}")
        
        job = BatchJob.from_row(response.data[0])
        logger.info(
            f"Registered batch job: {batch_id} (stage={stage.value}, "
            f"articles={article_count}, requests={request_count})"
        )
        return job
    
    def mark_creation_started(
        self,
        stage: BatchStage | str,
        *,
        article_count: int = 0,
        model: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BatchJob:
        """Mark batch creation as started for a stage.
        
        Creates a temporary "CREATING" status record to prevent concurrent
        batch creation attempts. This should be called BEFORE starting the
        batch creation process, then updated to PENDING once successful.
        
        Args:
            stage: Pipeline stage (facts, knowledge, summary)
            article_count: Estimated number of articles
            model: Model to be used
            metadata: Additional metadata
            
        Returns:
            Created BatchJob record with CREATING status
            
        Raises:
            Exception: If insert fails
        """
        if isinstance(stage, str):
            stage = BatchStage(stage)
        
        # Use a temporary batch_id that will be updated later
        temp_batch_id = f"creating_{stage.value}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        
        now = _now_iso()
        record = {
            "batch_id": temp_batch_id,
            "stage": stage.value,
            "status": BatchStatus.CREATING.value,
            "article_count": article_count,
            "request_count": 0,
            "model": model,
            "submitted_at": now,
            "max_retries": 1,
            "metadata": {**(metadata or {}), "creation_started_at": now},
        }
        
        response = self.client.table(self.TABLE_NAME).insert(record).execute()
        
        if not response.data:
            raise Exception(f"Failed to mark creation started for {stage.value}")
        
        job = BatchJob.from_row(response.data[0])
        logger.info(f"Marked batch creation started: {stage.value} (temp_id={temp_batch_id})")
        return job
    
    def mark_creation_completed(
        self,
        creating_batch_id: str,
        actual_batch_id: str,
        *,
        request_count: int = 0,
        input_file_id: Optional[str] = None,
    ) -> Optional[BatchJob]:
        """Update a CREATING batch to PENDING with actual batch ID.
        
        Called after successful batch creation to update the temporary
        CREATING record with the actual OpenAI batch ID and transition
        to PENDING status.
        
        Args:
            creating_batch_id: The temporary batch_id from mark_creation_started()
            actual_batch_id: The actual OpenAI batch ID
            request_count: Actual number of requests in the batch
            input_file_id: OpenAI input file ID
            
        Returns:
            Updated BatchJob, or None if not found
        """
        update = {
            "batch_id": actual_batch_id,
            "status": BatchStatus.PENDING.value,
            "request_count": request_count,
            "input_file_id": input_file_id,
        }
        
        response = (
            self.client.table(self.TABLE_NAME)
            .update(update)
            .eq("batch_id", creating_batch_id)
            .execute()
        )
        
        if response.data:
            logger.info(f"Marked batch creation completed: {creating_batch_id} → {actual_batch_id}")
            return BatchJob.from_row(response.data[0])
        return None
    
    def get_batch(self, batch_id: str) -> Optional[BatchJob]:
        """Get a batch job by OpenAI batch ID.
        
        Args:
            batch_id: OpenAI batch ID
            
        Returns:
            BatchJob if found, None otherwise
        """
        response = (
            self.client.table(self.TABLE_NAME)
            .select("*")
            .eq("batch_id", batch_id)
            .limit(1)
            .execute()
        )
        
        if response.data:
            return BatchJob.from_row(response.data[0])
        return None
    
    def get_pending_batches(
        self,
        stage: Optional[BatchStage | str] = None,
        limit: int = 50,
    ) -> List[BatchJob]:
        """Get batches that need status checking or processing.
        
        Returns batches with status 'pending' or 'completed' (ready to process).
        
        Args:
            stage: Optional filter by stage
            limit: Maximum number of results
            
        Returns:
            List of BatchJob records ordered by creation time
        """
        query = (
            self.client.table(self.TABLE_NAME)
            .select("*")
            .in_("status", [BatchStatus.PENDING.value, BatchStatus.COMPLETED.value])
            .order("created_at", desc=False)
            .limit(limit)
        )
        
        if stage:
            if isinstance(stage, str):
                stage = BatchStage(stage)
            query = query.eq("stage", stage.value)
        
        response = query.execute()
        return [BatchJob.from_row(row) for row in (response.data or [])]
    
    def get_batches_by_status(
        self,
        status: BatchStatus | str,
        stage: Optional[BatchStage | str] = None,
        limit: int = 50,
    ) -> List[BatchJob]:
        """Get batches with a specific status.
        
        Args:
            status: Status to filter by
            stage: Optional filter by stage
            limit: Maximum number of results
            
        Returns:
            List of BatchJob records
        """
        if isinstance(status, str):
            status = BatchStatus(status)
        
        query = (
            self.client.table(self.TABLE_NAME)
            .select("*")
            .eq("status", status.value)
            .order("created_at", desc=False)
            .limit(limit)
        )
        
        if stage:
            if isinstance(stage, str):
                stage = BatchStage(stage)
            query = query.eq("stage", stage.value)
        
        response = query.execute()
        return [BatchJob.from_row(row) for row in (response.data or [])]

    def has_active_batches(
        self,
        stage: BatchStage | str,
        *,
        statuses: Optional[List[BatchStatus | str]] = None,
    ) -> bool:
        """Return True when a stage already has in-flight batches.

        Active batches are those that are creating, pending, completed (awaiting processing),
        or currently being processed. This is used to prevent overlapping batch
        submissions that churn through the same backlog.
        """
        if isinstance(stage, str):
            stage = BatchStage(stage)

        active_statuses = statuses or [
            BatchStatus.CREATING,
            BatchStatus.PENDING,
            BatchStatus.COMPLETED,
            BatchStatus.PROCESSING,
        ]

        status_values = [s.value if isinstance(s, BatchStatus) else str(s) for s in active_statuses]

        response = (
            self.client.table(self.TABLE_NAME)
            .select("id")
            .eq("stage", stage.value)
            .in_("status", status_values)
            .limit(1)
            .execute()
        )

        return bool(getattr(response, "data", []) or [])
    
    def get_failed_batches_for_retry(self, limit: int = 10) -> List[BatchJob]:
        """Get failed batches that are eligible for retry.
        
        Returns batches where retry_count < max_retries.
        
        Args:
            limit: Maximum number of results
            
        Returns:
            List of BatchJob records eligible for retry
        """
        # Supabase doesn't support column-to-column comparison in filters,
        # so we fetch failed batches and filter in Python
        response = (
            self.client.table(self.TABLE_NAME)
            .select("*")
            .eq("status", BatchStatus.FAILED.value)
            .order("created_at", desc=False)
            .limit(limit * 2)  # Fetch extra to account for filtering
            .execute()
        )
        
        jobs = [BatchJob.from_row(row) for row in (response.data or [])]
        return [job for job in jobs if job.retry_count < job.max_retries][:limit]
    
    def mark_completed(
        self,
        batch_id: str,
        *,
        output_file_id: Optional[str] = None,
    ) -> Optional[BatchJob]:
        """Mark a batch as completed by OpenAI (ready to process).
        
        Args:
            batch_id: OpenAI batch ID
            output_file_id: OpenAI output file ID
            
        Returns:
            Updated BatchJob, or None if not found
        """
        update = {
            "status": BatchStatus.COMPLETED.value,
            "completed_at": _now_iso(),
        }
        if output_file_id:
            update["output_file_id"] = output_file_id
        
        response = (
            self.client.table(self.TABLE_NAME)
            .update(update)
            .eq("batch_id", batch_id)
            .execute()
        )
        
        if response.data:
            logger.info(f"Marked batch {batch_id} as completed")
            return BatchJob.from_row(response.data[0])
        return None
    
    def mark_processing(self, batch_id: str) -> Optional[BatchJob]:
        """Mark a batch as currently being processed.
        
        Args:
            batch_id: OpenAI batch ID
            
        Returns:
            Updated BatchJob, or None if not found
        """
        response = (
            self.client.table(self.TABLE_NAME)
            .update({"status": BatchStatus.PROCESSING.value})
            .eq("batch_id", batch_id)
            .execute()
        )
        
        if response.data:
            logger.info(f"Marked batch {batch_id} as processing")
            return BatchJob.from_row(response.data[0])
        return None
    
    def mark_processed(
        self,
        batch_id: str,
        *,
        items_processed: int = 0,
        items_skipped: int = 0,
        items_failed: int = 0,
    ) -> Optional[BatchJob]:
        """Mark a batch as successfully processed.
        
        Args:
            batch_id: OpenAI batch ID
            items_processed: Number of items successfully processed
            items_skipped: Number of items skipped (already existed, etc.)
            items_failed: Number of items that failed
            
        Returns:
            Updated BatchJob, or None if not found
        """
        update = {
            "status": BatchStatus.PROCESSED.value,
            "processed_at": _now_iso(),
            "items_processed": items_processed,
            "items_skipped": items_skipped,
            "items_failed": items_failed,
            "error_message": None,  # Clear any previous error
        }
        
        response = (
            self.client.table(self.TABLE_NAME)
            .update(update)
            .eq("batch_id", batch_id)
            .execute()
        )
        
        if response.data:
            logger.info(
                f"Marked batch {batch_id} as processed: "
                f"{items_processed} processed, {items_skipped} skipped, {items_failed} failed"
            )
            return BatchJob.from_row(response.data[0])
        return None
    
    def mark_failed(
        self,
        batch_id: str,
        error_message: str,
        *,
        increment_retry: bool = True,
    ) -> Optional[BatchJob]:
        """Mark a batch as failed.
        
        Args:
            batch_id: OpenAI batch ID
            error_message: Description of the failure
            increment_retry: Whether to increment retry_count
            
        Returns:
            Updated BatchJob, or None if not found
        """
        # First get current retry count
        current = self.get_batch(batch_id)
        if not current:
            return None
        
        new_retry_count = current.retry_count + 1 if increment_retry else current.retry_count
        
        update = {
            "status": BatchStatus.FAILED.value,
            "error_message": error_message[:1000],  # Truncate long messages
            "retry_count": new_retry_count,
        }
        
        response = (
            self.client.table(self.TABLE_NAME)
            .update(update)
            .eq("batch_id", batch_id)
            .execute()
        )
        
        if response.data:
            logger.warning(
                f"Marked batch {batch_id} as failed (retry {new_retry_count}/{current.max_retries}): "
                f"{error_message[:100]}"
            )
            return BatchJob.from_row(response.data[0])
        return None
    
    def mark_cancelled(self, batch_id: str) -> Optional[BatchJob]:
        """Mark a batch as cancelled.
        
        Args:
            batch_id: OpenAI batch ID
            
        Returns:
            Updated BatchJob, or None if not found
        """
        response = (
            self.client.table(self.TABLE_NAME)
            .update({"status": BatchStatus.CANCELLED.value})
            .eq("batch_id", batch_id)
            .execute()
        )
        
        if response.data:
            logger.info(f"Marked batch {batch_id} as cancelled")
            return BatchJob.from_row(response.data[0])
        return None
    
    def reset_for_retry(self, batch_id: str) -> Optional[BatchJob]:
        """Reset a failed batch for retry.
        
        Sets status back to 'pending' so it can be processed again.
        
        Args:
            batch_id: OpenAI batch ID
            
        Returns:
            Updated BatchJob, or None if not found
        """
        response = (
            self.client.table(self.TABLE_NAME)
            .update({
                "status": BatchStatus.PENDING.value,
                "error_message": None,
            })
            .eq("batch_id", batch_id)
            .execute()
        )
        
        if response.data:
            logger.info(f"Reset batch {batch_id} for retry")
            return BatchJob.from_row(response.data[0])
        return None
    
    def get_recent_batches(
        self,
        stage: Optional[BatchStage | str] = None,
        limit: int = 20,
    ) -> List[BatchJob]:
        """Get recent batches ordered by creation time.
        
        Args:
            stage: Optional filter by stage
            limit: Maximum number of results
            
        Returns:
            List of BatchJob records, newest first
        """
        query = (
            self.client.table(self.TABLE_NAME)
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
        )
        
        if stage:
            if isinstance(stage, str):
                stage = BatchStage(stage)
            query = query.eq("stage", stage.value)
        
        response = query.execute()
        return [BatchJob.from_row(row) for row in (response.data or [])]
    
    def get_stale_creating_batches(
        self,
        max_age_minutes: int = 30,
        stage: Optional[BatchStage | str] = None,
    ) -> List[BatchJob]:
        """Get batches stuck in CREATING status for too long.
        
        These batches indicate a batch creation process that hung or crashed
        before completing. They should be marked as failed to unblock the pipeline.
        
        Args:
            max_age_minutes: Consider batches stale after this many minutes in CREATING status
            stage: Optional filter by stage
            
        Returns:
            List of stale BatchJob records
        """
        from datetime import timedelta
        
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        
        query = (
            self.client.table(self.TABLE_NAME)
            .select("*")
            .eq("status", BatchStatus.CREATING.value)
            .lt("created_at", cutoff_time.isoformat())
        )
        
        if stage:
            if isinstance(stage, str):
                stage = BatchStage(stage)
            query = query.eq("stage", stage.value)
        
        response = query.execute()
        rows = getattr(response, "data", []) or []
        
        jobs = [BatchJob.from_row(row) for row in rows]
        
        if jobs:
            logger.warning(
                f"Found {len(jobs)} batches stuck in CREATING status "
                f"for >{max_age_minutes} minutes"
            )
        
        return jobs
