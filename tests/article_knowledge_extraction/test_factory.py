"""Payload parsing + validation for the article_knowledge_extraction service."""

from __future__ import annotations

import pytest

from src.functions.article_knowledge_extraction.core.factory import (
    poll_request_from_payload,
    submit_request_from_payload,
    worker_request_from_payload,
)


def _minimal_submit_payload() -> dict:
    return {
        "article": {"text": "Josh Allen threw three touchdowns."},
        "llm": {"provider": "openai", "model": "gpt-5.4-mini", "api_key": "sk-test"},
        "supabase": {"url": "https://x.supabase.co", "key": "service-role"},
    }


def test_submit_minimal_payload_parses():
    req = submit_request_from_payload(_minimal_submit_payload())
    assert req.article.text.startswith("Josh Allen")
    assert req.llm.model == "gpt-5.4-mini"
    assert req.supabase.jobs_table == "article_knowledge_extraction_jobs"
    assert req.options.resolve_entities is True


def test_submit_missing_article_text_raises():
    payload = _minimal_submit_payload()
    payload["article"] = {}
    with pytest.raises(ValueError):
        submit_request_from_payload(payload)


def test_submit_article_too_long_raises():
    payload = _minimal_submit_payload()
    payload["article"] = {"text": "x" * 200_001}
    with pytest.raises(ValueError):
        submit_request_from_payload(payload)


def test_submit_missing_llm_api_key_raises():
    payload = _minimal_submit_payload()
    payload["llm"] = {"provider": "openai", "model": "gpt-5.4-mini"}
    with pytest.raises(ValueError):
        submit_request_from_payload(payload)


def test_submit_missing_supabase_raises():
    payload = _minimal_submit_payload()
    payload.pop("supabase")
    with pytest.raises(ValueError):
        submit_request_from_payload(payload)


def test_submit_invalid_confidence_threshold_raises():
    payload = _minimal_submit_payload()
    payload["options"] = {"confidence_threshold": 1.5}
    with pytest.raises(ValueError):
        submit_request_from_payload(payload)


def test_submit_honors_options_overrides():
    payload = _minimal_submit_payload()
    payload["options"] = {
        "max_topics": 2,
        "max_entities": 8,
        "resolve_entities": False,
        "confidence_threshold": 0.9,
    }
    req = submit_request_from_payload(payload)
    assert req.options.max_topics == 2
    assert req.options.resolve_entities is False
    assert req.options.confidence_threshold == 0.9


def test_poll_requires_job_id_and_supabase():
    with pytest.raises(ValueError):
        poll_request_from_payload({"supabase": {"url": "u", "key": "k"}})
    with pytest.raises(ValueError):
        poll_request_from_payload({"job_id": "abc"})
    req = poll_request_from_payload(
        {"job_id": "abc", "supabase": {"url": "u", "key": "k"}}
    )
    assert req.job_id == "abc"


def test_worker_requires_job_id_and_supabase():
    with pytest.raises(ValueError):
        worker_request_from_payload({})
    req = worker_request_from_payload(
        {"job_id": "abc", "supabase": {"url": "u", "key": "k"}}
    )
    assert req.job_id == "abc"
