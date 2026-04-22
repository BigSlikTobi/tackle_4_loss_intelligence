"""Build request models from raw HTTP payloads."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .config import (
    ArticleInput,
    ExtractionOptions,
    LLMConfig,
    PollRequest,
    SubmitRequest,
    SupabaseConfig,
    WorkerRequest,
)


def _parse_llm(payload: Optional[Dict[str, Any]]) -> Optional[LLMConfig]:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("llm must be an object when provided")
    return LLMConfig(
        provider=payload.get("provider", "openai"),
        model=payload.get("model", "gpt-5.4-mini"),
        api_key=payload.get("api_key", ""),
        parameters=payload.get("parameters") or {},
        timeout_seconds=int(payload.get("timeout_seconds", 60)),
        max_retries=int(payload.get("max_retries", 2)),
    )


def _parse_supabase(payload: Optional[Dict[str, Any]]) -> Optional[SupabaseConfig]:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("supabase must be an object when provided")
    return SupabaseConfig(
        url=payload.get("url", ""),
        key=payload.get("key", ""),
        jobs_table=payload.get("jobs_table", "article_knowledge_extraction_jobs"),
    )


def _parse_article(payload: Optional[Dict[str, Any]]) -> ArticleInput:
    if not isinstance(payload, dict):
        raise ValueError("article must be an object containing at least 'text'")
    return ArticleInput(
        text=payload.get("text", ""),
        article_id=payload.get("article_id"),
        title=payload.get("title"),
        url=payload.get("url"),
    )


def _parse_options(payload: Optional[Dict[str, Any]]) -> ExtractionOptions:
    payload = payload or {}
    if not isinstance(payload, dict):
        raise ValueError("options must be an object when provided")
    return ExtractionOptions(
        max_topics=int(payload.get("max_topics", 5)),
        max_entities=int(payload.get("max_entities", 15)),
        resolve_entities=bool(payload.get("resolve_entities", True)),
        confidence_threshold=float(payload.get("confidence_threshold", 0.6)),
    )


def submit_request_from_payload(payload: Dict[str, Any]) -> SubmitRequest:
    request = SubmitRequest(
        article=_parse_article(payload.get("article")),
        options=_parse_options(payload.get("options")),
        llm=_parse_llm(payload.get("llm")),
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
