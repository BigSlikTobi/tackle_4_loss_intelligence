"""Validate /submit, /poll, /worker payload parsing."""

from __future__ import annotations

import pytest

from src.functions.url_content_extraction_service.core.factory import (
    poll_request_from_payload,
    submit_request_from_payload,
    worker_request_from_payload,
)


def _supabase() -> dict:
    return {"url": "https://x.supabase.co", "key": "k"}


def test_submit_minimal_ok():
    req = submit_request_from_payload(
        {"urls": ["https://example.com/a"], "supabase": _supabase()}
    )
    assert req.urls == ["https://example.com/a"]
    assert req.options.timeout_seconds == 45
    assert req.supabase.jobs_table == "extraction_jobs"


def test_submit_rejects_empty_urls():
    with pytest.raises(ValueError, match="urls must be a non-empty list"):
        submit_request_from_payload({"urls": [], "supabase": _supabase()})


def test_submit_rejects_too_many_urls():
    with pytest.raises(ValueError, match="exceeds the 20 per-job limit"):
        submit_request_from_payload(
            {"urls": [f"https://e.com/{i}" for i in range(21)], "supabase": _supabase()}
        )


def test_submit_rejects_blank_url_entry():
    with pytest.raises(ValueError, match="non-empty string"):
        submit_request_from_payload(
            {"urls": ["https://e.com", "   "], "supabase": _supabase()}
        )


def test_submit_rejects_unbounded_timeout():
    with pytest.raises(ValueError, match="timeout_seconds must be <="):
        submit_request_from_payload(
            {
                "urls": ["https://e.com"],
                "options": {"timeout_seconds": 10_000},
                "supabase": _supabase(),
            }
        )


def test_submit_rejects_missing_supabase():
    with pytest.raises(ValueError, match="supabase.url and supabase.key are required"):
        submit_request_from_payload({"urls": ["https://e.com"]})


def test_poll_requires_job_id_and_supabase():
    with pytest.raises(ValueError, match="job_id is required"):
        poll_request_from_payload({"supabase": _supabase()})
    with pytest.raises(ValueError, match="supabase"):
        poll_request_from_payload({"job_id": "abc"})


def test_worker_requires_job_id_and_supabase():
    with pytest.raises(ValueError):
        worker_request_from_payload({"job_id": ""})
    req = worker_request_from_payload({"job_id": "abc", "supabase": _supabase()})
    assert req.job_id == "abc"
