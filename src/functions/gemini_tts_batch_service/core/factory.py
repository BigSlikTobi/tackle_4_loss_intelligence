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


def _build_supabase(payload: Optional[Dict[str, Any]]) -> Optional[SupabaseConfig]:
    """Build SupabaseConfig from runtime env, ignoring caller-supplied URLs.

    The Cloud Function is bound to one Supabase project via its deployment
    env (``SUPABASE_URL`` + ``SUPABASE_SERVICE_ROLE_KEY``). Both values are
    read here; nothing is taken from the request body. This closes a
    confused-deputy vector where an authenticated caller could point the
    function's service-role token at an attacker-controlled host by passing
    ``supabase.url`` in the payload.

    The optional ``jobs_table`` override is still honoured because it's a
    low-risk discriminator inside the same project (and existing callers
    rely on the default ``extraction_jobs``).
    """
    if payload is not None and not isinstance(payload, dict):
        raise ValueError("supabase must be an object when provided")
    jobs_table = "extraction_jobs"
    if isinstance(payload, dict):
        jobs_table = str(payload.get("jobs_table") or jobs_table)
    return SupabaseConfig(
        url=os.getenv("SUPABASE_URL", ""),
        key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
        jobs_table=jobs_table,
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
        supabase=_build_supabase(payload.get("supabase")),
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
        supabase=_build_supabase(payload.get("supabase")),
    )
    request.validate()
    return request


def worker_request_from_payload(payload: Dict[str, Any]) -> WorkerRequest:
    request = WorkerRequest(
        job_id=str(payload.get("job_id") or ""),
        supabase=_build_supabase(payload.get("supabase")),
    )
    request.validate()
    return request
