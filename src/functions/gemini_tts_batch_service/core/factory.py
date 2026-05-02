"""Build request models from raw HTTP payloads."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from src.shared.jobs.contracts import SupabaseConfig

from .. import JOB_ACTIONS
from .config import (
    CreateInput,
    PollRequest,
    ProcessInput,
    StatusInput,
    SubmitRequest,
    WorkerRequest,
)


def _parse_supabase(payload: Optional[Dict[str, Any]]) -> Optional[SupabaseConfig]:
    """Hydrate SupabaseConfig from payload url/jobs_table + env-provided key.

    Callers never send the service-role key in the request body; the function
    reads it from its own runtime env (``SUPABASE_SERVICE_ROLE_KEY``).
    """
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("supabase must be an object when provided")
    return SupabaseConfig(
        url=payload.get("url", ""),
        key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
        jobs_table=payload.get("jobs_table", "extraction_jobs"),
    )


def _parse_storage(payload: Optional[Dict[str, Any]]) -> Dict[str, str]:
    payload = payload or {}
    if not isinstance(payload, dict):
        raise ValueError("storage must be an object when provided")
    return {
        "bucket": str(payload.get("bucket") or "audio"),
        "path_prefix": str(payload.get("path_prefix") or "gemini-tts-batch"),
    }


def _parse_items(raw: Any) -> list:
    if not isinstance(raw, list):
        raise ValueError("items must be a list of objects")
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("every entry in items must be an object")
        out.append(dict(entry))
    return out


def submit_request_from_payload(payload: Dict[str, Any]) -> SubmitRequest:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    action = str(payload.get("action") or "")
    if action not in JOB_ACTIONS:
        raise ValueError(f"action must be one of: {', '.join(JOB_ACTIONS)}")

    request = SubmitRequest(
        action=action,
        supabase=_parse_supabase(payload.get("supabase")),
    )

    if action == "create":
        request.create_input = CreateInput(
            model_name=str(payload.get("model_name") or ""),
            voice_name=str(payload.get("voice_name") or "Charon"),
            items=_parse_items(payload.get("items")),
        )
    elif action == "status":
        request.status_input = StatusInput(
            batch_id=str(payload.get("batch_id") or ""),
        )
    elif action == "process":
        storage = _parse_storage(payload.get("storage"))
        request.process_input = ProcessInput(
            batch_id=str(payload.get("batch_id") or ""),
            bucket=storage["bucket"],
            path_prefix=storage["path_prefix"],
        )

    request.validate()
    return request


def poll_request_from_payload(payload: Dict[str, Any]) -> PollRequest:
    request = PollRequest(
        job_id=str(payload.get("job_id") or ""),
        supabase=_parse_supabase(payload.get("supabase")),
    )
    request.validate()
    return request


def worker_request_from_payload(payload: Dict[str, Any]) -> WorkerRequest:
    request = WorkerRequest(
        job_id=str(payload.get("job_id") or ""),
        supabase=_parse_supabase(payload.get("supabase")),
    )
    request.validate()
    return request
