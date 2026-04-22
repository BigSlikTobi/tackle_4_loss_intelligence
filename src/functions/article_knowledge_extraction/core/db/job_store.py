"""CRUD for the ephemeral article knowledge extraction jobs table.

All operations are per-request: callers construct a JobStore with a Supabase
client built from the SupabaseConfig in the HTTP payload. No module-global
client is used.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..config import SupabaseConfig
from ..contracts.job import JobStatus

logger = logging.getLogger(__name__)


def build_client(config: SupabaseConfig):
    """Create a request-scoped Supabase client from explicit credentials."""
    try:
        from supabase import create_client
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "supabase package is not installed. pip install supabase"
        ) from exc
    return create_client(config.url, config.key)


class JobStore:
    def __init__(self, config: SupabaseConfig, client=None):
        self._config = config
        self._client = client or build_client(config)

    @property
    def _table(self):
        return self._client.table(self._config.jobs_table)

    # --- writes --------------------------------------------------------

    def create_job(self, input_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a new `queued` job and return the persisted row.

        The `input_payload` is stored as-is in the jsonb column so the worker
        can rehydrate the article + options + llm reference later.
        """
        row = {
            "status": JobStatus.QUEUED.value,
            "input": input_payload,
        }
        response = self._table.insert(row).execute()
        if not response.data:
            raise RuntimeError("create_job: insert returned no data")
        job = response.data[0]
        logger.info("Created job %s (status=queued)", job.get("job_id"))
        return job

    def mark_running(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Claim a job for processing. Only transitions queued -> running."""
        now = _iso_now()
        response = (
            self._table.update(
                {
                    "status": JobStatus.RUNNING.value,
                    "started_at": now,
                    "updated_at": now,
                }
            )
            .eq("job_id", job_id)
            .eq("status", JobStatus.QUEUED.value)
            .execute()
        )
        rows = response.data or []
        if not rows:
            logger.info("Job %s could not be marked running (already taken or terminal)", job_id)
            return None
        # Bump attempts separately (Supabase REST can't do +1 atomically here;
        # an extra read is fine since this row is job-local).
        self._increment_attempts(job_id)
        return rows[0]

    def _increment_attempts(self, job_id: str) -> None:
        try:
            current = (
                self._table.select("attempts").eq("job_id", job_id).single().execute()
            )
            attempts = int((current.data or {}).get("attempts", 0)) + 1
            self._table.update({"attempts": attempts}).eq("job_id", job_id).execute()
        except Exception:
            logger.debug("Failed to increment attempts for %s", job_id, exc_info=True)

    def mark_succeeded(self, job_id: str, result: Dict[str, Any]) -> None:
        now = _iso_now()
        self._table.update(
            {
                "status": JobStatus.SUCCEEDED.value,
                "result": result,
                "error": None,
                "finished_at": now,
                "updated_at": now,
            }
        ).eq("job_id", job_id).execute()
        logger.info("Job %s succeeded", job_id)

    def mark_failed(self, job_id: str, error: Dict[str, Any]) -> None:
        now = _iso_now()
        self._table.update(
            {
                "status": JobStatus.FAILED.value,
                "error": error,
                "finished_at": now,
                "updated_at": now,
            }
        ).eq("job_id", job_id).execute()
        logger.warning("Job %s failed: %s", job_id, error.get("message"))

    # --- reads ---------------------------------------------------------

    def peek(self, job_id: str) -> Optional[Dict[str, Any]]:
        response = self._table.select("*").eq("job_id", job_id).limit(1).execute()
        rows = response.data or []
        return rows[0] if rows else None

    def consume_terminal(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Atomically delete-and-return a terminal job. Returns None if the
        job is still running, does not exist, or expired."""
        response = self._client.rpc(
            "consume_article_knowledge_job",
            {"p_job_id": job_id},
        ).execute()
        rows = response.data or []
        if not rows:
            return None
        return rows[0] if isinstance(rows, list) else rows

    def list_stale(
        self,
        queued_older_than_seconds: int = 120,
        running_older_than_seconds: int = 600,
        max_attempts: int = 3,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Find jobs that are apparently stuck and need to be re-dispatched."""
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        queued_cutoff = (now - timedelta(seconds=queued_older_than_seconds)).isoformat()
        running_cutoff = (now - timedelta(seconds=running_older_than_seconds)).isoformat()

        stale_queued = (
            self._table.select("*")
            .eq("status", JobStatus.QUEUED.value)
            .lt("created_at", queued_cutoff)
            .lt("attempts", max_attempts)
            .limit(limit)
            .execute()
        )
        stale_running = (
            self._table.select("*")
            .eq("status", JobStatus.RUNNING.value)
            .lt("started_at", running_cutoff)
            .lt("attempts", max_attempts)
            .limit(limit)
            .execute()
        )
        return (stale_queued.data or []) + (stale_running.data or [])

    def delete_expired(self) -> int:
        """Delete all rows past `expires_at`. Returns deleted row count."""
        now_iso = _iso_now()
        response = (
            self._table.delete()
            .lt("expires_at", now_iso)
            .execute()
        )
        deleted = response.data or []
        count = len(deleted) if isinstance(deleted, list) else 0
        if count:
            logger.info("Deleted %d expired job rows", count)
        return count


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
