"""Worker-side orchestration for a single gemini_tts_batch job.

Loads the queued row, claims it (queued -> running), dispatches to the legacy
``TTSBatchService`` based on the stored ``action``, persists terminal state.
Idempotent: if the job is already terminal, no-op.

Three actions are supported:
  - ``create``  → submits a Gemini batch (returns batch_id + initial state).
  - ``status``  → reads current Gemini batch state.
  - ``process`` → downloads completed batch output and uploads MP3s to the
                  storage bucket the caller chose.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Dict, Optional

from src.shared.jobs.contracts import JobStatus, SupabaseConfig
from src.shared.jobs.store import JobStore

from ..contracts.result import JobResult

SERVICE_NAME = "gemini_tts_batch"
JOB_ACTIONS = ("create", "status", "process")

logger = logging.getLogger(__name__)


# Pluggable seam so the worker can be unit-tested without the legacy service
# (which depends on google-genai, pydub, supabase).
DispatchFn = Callable[[str, Dict[str, Any]], Dict[str, Any]]


def run_job(
    job_id: str,
    supabase_config: SupabaseConfig,
    *,
    dispatch_fn: Optional[DispatchFn] = None,
    store: Optional[JobStore] = None,
) -> Dict[str, Any]:
    """Run one TTS batch job. Returns a summary dict."""
    store = store or JobStore(supabase_config, service=SERVICE_NAME)
    row = store.peek(job_id)
    if row is None:
        logger.warning("run_job: job %s not found (expired or consumed)", job_id)
        return {"job_id": job_id, "status": "not_found"}

    status = row.get("status")
    if status in (JobStatus.SUCCEEDED.value, JobStatus.FAILED.value):
        logger.info("run_job: job %s already terminal (%s)", job_id, status)
        return {"job_id": job_id, "status": status, "idempotent_skip": True}

    claimed = store.mark_running(job_id)
    if claimed is None:
        logger.info("run_job: could not claim job %s", job_id)
        return {"job_id": job_id, "status": "not_claimed"}

    input_payload = row.get("input") or {}
    try:
        action = _validate_input(input_payload)
    except ValueError as exc:
        store.mark_failed(
            job_id,
            {"code": "invalid_input", "message": str(exc), "retryable": False},
        )
        return {"job_id": job_id, "status": "failed", "reason": "invalid_input"}

    dispatch = dispatch_fn or _default_dispatch
    try:
        payload = dispatch(action, input_payload)
    except ValueError as exc:
        # Pydantic validation errors and other caller-fixable problems.
        logger.warning("Job %s rejected: %s", job_id, exc)
        store.mark_failed(
            job_id,
            {"code": "validation_error", "message": str(exc), "retryable": False},
        )
        return {"job_id": job_id, "status": "failed", "reason": "validation_error"}
    except RuntimeError as exc:
        # Upstream Gemini errors are typically transient.
        logger.warning("Job %s upstream error: %s", job_id, exc)
        store.mark_failed(
            job_id,
            {"code": "upstream_error", "message": str(exc), "retryable": True},
        )
        return {"job_id": job_id, "status": "failed", "reason": "upstream_error"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Job %s crashed during action=%s", job_id, action)
        store.mark_failed(
            job_id,
            {"code": exc.__class__.__name__, "message": str(exc), "retryable": True},
        )
        return {"job_id": job_id, "status": "failed", "reason": "exception"}

    result = JobResult(action=action, payload=payload).to_dict()
    store.mark_succeeded(job_id, result)
    return {"job_id": job_id, "status": "succeeded", "action": action}


def _validate_input(payload: Dict[str, Any]) -> str:
    """Cheap, dependency-free validation of stored input. Returns the action."""
    action = payload.get("action")
    if action not in JOB_ACTIONS:
        raise ValueError(f"stored input has invalid action: {action!r}")
    if action == "process":
        # Storage credentials live in the worker's env; check eagerly so we
        # fail fast with a clear message rather than deep inside the legacy
        # supabase client.
        storage_url = (
            os.getenv("STORAGE_SUPABASE_URL")
            or os.getenv("SUPABASE_URL", "")
        )
        storage_key = (
            os.getenv("STORAGE_SUPABASE_KEY")
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        )
        if not storage_url or not storage_key:
            raise ValueError(
                "Storage credentials not configured: set STORAGE_SUPABASE_URL/"
                "STORAGE_SUPABASE_KEY (or SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY) "
                "in the worker environment."
            )
    return action


def _default_dispatch(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build the legacy pydantic request and call into ``TTSBatchService``.

    Imports are lazy so tests that patch ``_default_dispatch`` (or pass their
    own ``dispatch_fn``) don't pull in google-genai / pydub.
    """
    from src.functions.gemini_tts_batch.core.config import (
        CreateBatchRequest,
        ProcessBatchRequest,
        StatusBatchRequest,
        SupabaseStorageConfig,
    )
    from src.functions.gemini_tts_batch.core.service import TTSBatchService

    service = TTSBatchService()
    try:
        if action == "create":
            request = CreateBatchRequest(
                action="create",
                model_name=payload.get("model_name", ""),
                voice_name=payload.get("voice_name", "Charon"),
                items=payload.get("items") or [],
            )
            return asyncio.run(service.create_batch(request))
        if action == "status":
            request = StatusBatchRequest(
                action="status",
                batch_id=payload.get("batch_id", ""),
            )
            return asyncio.run(service.check_status(request))
        # action == "process"
        storage_url = (
            os.getenv("STORAGE_SUPABASE_URL")
            or os.getenv("SUPABASE_URL", "")
        )
        storage_key = (
            os.getenv("STORAGE_SUPABASE_KEY")
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        )
        request = ProcessBatchRequest(
            action="process",
            batch_id=payload.get("batch_id", ""),
            supabase=SupabaseStorageConfig(
                url=storage_url,
                key=storage_key,
                bucket=payload.get("bucket") or "audio",
                path_prefix=payload.get("path_prefix") or "gemini-tts-batch",
            ),
        )
        return asyncio.run(service.process_batch(request))
    except ValueError:
        raise
    except Exception as exc:
        # Pydantic v2 raises pydantic.ValidationError, which is a ValueError
        # subclass and is already caught above. Other pydantic-construction
        # errors should be surfaced as caller-fixable.
        if exc.__class__.__name__ == "ValidationError":
            raise ValueError(str(exc)) from exc
        raise
