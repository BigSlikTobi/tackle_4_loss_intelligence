"""Build request models from raw HTTP payloads."""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.shared.jobs.contracts import SupabaseConfig

from .config import (
    ExtractionOptions,
    PollRequest,
    SubmitRequest,
    WorkerRequest,
)


def _parse_supabase(payload: Optional[Dict[str, Any]]) -> Optional[SupabaseConfig]:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("supabase must be an object when provided")
    return SupabaseConfig(
        url=payload.get("url", ""),
        key=payload.get("key", ""),
        jobs_table=payload.get("jobs_table", "extraction_jobs"),
    )


def _parse_options(payload: Optional[Dict[str, Any]]) -> ExtractionOptions:
    payload = payload or {}
    if not isinstance(payload, dict):
        raise ValueError("options must be an object when provided")
    return ExtractionOptions(
        timeout_seconds=int(payload.get("timeout_seconds", 45)),
        force_playwright=bool(payload.get("force_playwright", False)),
        prefer_lightweight=bool(payload.get("prefer_lightweight", False)),
        max_paragraphs=int(payload.get("max_paragraphs", 120)),
        min_paragraph_chars=int(payload.get("min_paragraph_chars", 240)),
    )


def _parse_urls(payload: Any) -> list:
    if not isinstance(payload, list):
        raise ValueError("urls must be a list of strings")
    return [str(u) for u in payload]


def submit_request_from_payload(payload: Dict[str, Any]) -> SubmitRequest:
    request = SubmitRequest(
        urls=_parse_urls(payload.get("urls")),
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
