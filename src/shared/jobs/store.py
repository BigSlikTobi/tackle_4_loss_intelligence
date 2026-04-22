"""CRUD for the shared ephemeral extraction jobs table.

All operations are per-request: callers construct a JobStore with a Supabase
client built from a SupabaseConfig in the HTTP payload. No module-global
client is used. Multiple services share the table; each row is tagged with
a ``service`` column so per-service queries (peek/list_stale/delete_expired)
stay scoped. ``consume_terminal`` operates on the global uuid and only adds
the service filter as defense-in-depth.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .contracts import JobStatus, SupabaseConfig

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
    """Service-scoped CRUD over the shared ``extraction_jobs`` table."""

    def __init__(
        self,
        config: SupabaseConfig,
        client=None,
        *,
        service: str,
    ):
        if not service:
            raise ValueError("JobStore requires a non-empty service name")
        self._config = config
        self._client = client or build_client(config)
        self._service = service

    @property
    def service(self) -> str:
        return self._service

    @property
    def _table(self):
        return self._client.table(self._config.jobs_table)

    # --- writes --------------------------------------------------------

    def create_job(self, input_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a new ``queued`` job and return the persisted row."""
        row = {
            "status": JobStatus.QUEUED.value,
            "input": input_payload,
            "service": self._service,
        }
        response = self._table.insert(row).execute()
        if not response.data:
            raise RuntimeError("create_job: insert returned no data")
        job = response.data[0]
        logger.info("Created job %s (status=queued)", job.get("job_id"))
        return job

    def mark_running(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Atomically claim a job. Only transitions queued -> running."""
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
            logger.info(
                "Job %s could not be marked running (already taken or terminal)",
                job_id,
            )
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
        response = (
            self._table.select("*")
            .eq("job_id", job_id)
            .eq("service", self._service)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def consume_terminal(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Atomically delete-and-return a terminal job. Returns None if the
        job is still running, does not exist, or expired.

        Defense-in-depth: after the RPC returns, we double-check the row's
        ``service`` matches this store so callers can't accidentally consume
        a foreign-service job that happened to share the same uuid.
        """
        response = self._client.rpc(
            "consume_extraction_job",
            {"p_job_id": job_id},
        ).execute()
        rows = response.data or []
        if not rows:
            return None
        row = rows[0] if isinstance(rows, list) else rows
        row_service = row.get("service") if isinstance(row, dict) else None
        if row_service is not None and row_service != self._service:
            logger.warning(
                "consume_terminal: row service %r != expected %r for job %s",
                row_service,
                self._service,
                job_id,
            )
            return None
        return row

    def list_stale(
        self,
        queued_older_than_seconds: int = 120,
        running_older_than_seconds: int = 600,
        max_attempts: int = 3,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Find jobs that are apparently stuck and need to be re-dispatched."""
        now = datetime.now(timezone.utc)
        queued_cutoff = (now - timedelta(seconds=queued_older_than_seconds)).isoformat()
        running_cutoff = (now - timedelta(seconds=running_older_than_seconds)).isoformat()

        stale_queued = (
            self._table.select("*")
            .eq("service", self._service)
            .eq("status", JobStatus.QUEUED.value)
            .lt("created_at", queued_cutoff)
            .lt("attempts", max_attempts)
            .limit(limit)
            .execute()
        )
        stale_running = (
            self._table.select("*")
            .eq("service", self._service)
            .eq("status", JobStatus.RUNNING.value)
            .lt("started_at", running_cutoff)
            .lt("attempts", max_attempts)
            .limit(limit)
            .execute()
        )
        return (stale_queued.data or []) + (stale_running.data or [])

    def reset_stale_running(
        self,
        running_older_than_seconds: int = 600,
        max_attempts: int = 3,
    ) -> int:
        """Atomically flip stale ``running`` rows back to ``queued``.

        ``mark_running`` only claims rows currently in ``queued`` (atomic
        compare-and-set), so a worker that crashed mid-job leaves the row
        stuck in ``running`` forever from the requeue path's perspective.
        This method resets such rows to ``queued`` (and clears
        ``started_at``) so the next worker invocation can claim them
        normally. Returns the number of rows reset.
        """
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(seconds=running_older_than_seconds)
        ).isoformat()
        response = (
            self._table.update(
                {
                    "status": JobStatus.QUEUED.value,
                    "started_at": None,
                    "updated_at": _iso_now(),
                }
            )
            .eq("service", self._service)
            .eq("status", JobStatus.RUNNING.value)
            .lt("started_at", cutoff)
            .lt("attempts", max_attempts)
            .execute()
        )
        rows = response.data or []
        count = len(rows) if isinstance(rows, list) else 0
        if count:
            logger.info("Reset %d stale running rows back to queued", count)
        return count

    def delete_expired(self) -> int:
        """Delete this service's rows past `expires_at`. Returns deleted row count."""
        now_iso = _iso_now()
        response = (
            self._table.delete()
            .eq("service", self._service)
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
