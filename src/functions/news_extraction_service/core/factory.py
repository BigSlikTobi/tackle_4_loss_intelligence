"""Build request models from raw HTTP payloads."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.shared.jobs.contracts import SupabaseConfig

from .config import ExtractionOptions, PollRequest, SubmitRequest, WorkerRequest


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


def _coerce_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"expected an integer, got {value!r}")


def _coerce_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_since(value: Any) -> Optional[datetime]:
    """Parse a ``since`` value into a tz-aware UTC datetime.

    Accepts:
    - ISO 8601 strings with timezone offset (``2026-04-22T10:00:00+00:00``,
      ``2026-04-22T10:00:00Z``).
    - Already-parsed ``datetime`` instances.
    Naive datetimes / strings are rejected (validated downstream) to
    prevent ambiguous handoffs from the caller's watermark.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # Python <3.11 fromisoformat doesn't accept the trailing Z; normalize.
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"options.since must be an ISO 8601 string: {exc}")
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed
    raise ValueError("options.since must be an ISO 8601 string or datetime")


def _parse_options(payload: Optional[Dict[str, Any]]) -> ExtractionOptions:
    payload = payload or {}
    if not isinstance(payload, dict):
        raise ValueError("options must be an object when provided")
    return ExtractionOptions(
        source_filter=_coerce_str(payload.get("source_filter")),
        since=_coerce_since(payload.get("since")),
        max_articles=_coerce_int(payload.get("max_articles")),
        max_workers=_coerce_int(payload.get("max_workers")),
    )


def submit_request_from_payload(payload: Dict[str, Any]) -> SubmitRequest:
    request = SubmitRequest(
        options=_parse_options(payload.get("options")),
        supabase=_parse_supabase(payload.get("supabase")),
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
