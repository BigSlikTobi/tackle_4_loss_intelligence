"""Validate /submit, /poll, /worker payload parsing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.functions.news_extraction_service.core.factory import (
    poll_request_from_payload,
    submit_request_from_payload,
    worker_request_from_payload,
)


def _supabase() -> dict:
    return {"url": "https://x.supabase.co", "key": "k"}


def test_submit_minimal_ok():
    req = submit_request_from_payload({"supabase": _supabase()})
    # All option fields default to None.
    assert req.options.source_filter is None
    assert req.options.since is None
    assert req.supabase.jobs_table == "extraction_jobs"


def test_submit_carries_options_through():
    since = "2026-04-22T10:00:00+00:00"
    req = submit_request_from_payload(
        {
            "options": {
                "source_filter": "ESPN",
                "since": since,
                "max_articles": 50,
                "max_workers": 4,
            },
            "supabase": _supabase(),
        }
    )
    assert req.options.source_filter == "ESPN"
    assert req.options.since == datetime(2026, 4, 22, 10, 0, 0, tzinfo=timezone.utc)
    assert req.options.max_articles == 50
    assert req.options.max_workers == 4


def test_submit_silently_drops_legacy_dry_run_clear_flags():
    """Service is pure-extraction; legacy persistence toggles are ignored."""
    req = submit_request_from_payload(
        {
            "options": {"dry_run": True, "clear": True, "source_filter": "ESPN"},
            "supabase": _supabase(),
        }
    )
    # ExtractionOptions intentionally has no dry_run/clear attributes.
    assert not hasattr(req.options, "dry_run")
    assert not hasattr(req.options, "clear")
    assert req.options.source_filter == "ESPN"


def test_submit_silently_drops_legacy_days_back_flag():
    """days_back was replaced by since; old payloads must not break the parser."""
    req = submit_request_from_payload(
        {"options": {"days_back": 3}, "supabase": _supabase()}
    )
    assert not hasattr(req.options, "days_back")
    assert req.options.since is None


def test_submit_accepts_iso_z_suffix_since():
    req = submit_request_from_payload(
        {"options": {"since": "2026-04-22T10:00:00Z"}, "supabase": _supabase()}
    )
    assert req.options.since == datetime(2026, 4, 22, 10, 0, 0, tzinfo=timezone.utc)


def test_submit_rejects_naive_since():
    with pytest.raises(ValueError, match="timezone-aware"):
        submit_request_from_payload(
            {"options": {"since": "2026-04-22T10:00:00"}, "supabase": _supabase()}
        )


def test_submit_rejects_future_since():
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="must not be in the future"):
        submit_request_from_payload(
            {"options": {"since": future}, "supabase": _supabase()}
        )


def test_submit_rejects_too_old_since():
    with pytest.raises(ValueError, match="must be on or after"):
        submit_request_from_payload(
            {"options": {"since": "1990-01-01T00:00:00+00:00"}, "supabase": _supabase()}
        )


def test_submit_rejects_garbage_since():
    with pytest.raises(ValueError, match="ISO 8601"):
        submit_request_from_payload(
            {"options": {"since": "yesterday"}, "supabase": _supabase()}
        )


def test_submit_rejects_out_of_range_max_articles():
    with pytest.raises(ValueError, match="max_articles"):
        submit_request_from_payload(
            {"options": {"max_articles": 99999}, "supabase": _supabase()}
        )


def test_submit_rejects_out_of_range_max_workers():
    with pytest.raises(ValueError, match="max_workers"):
        submit_request_from_payload(
            {"options": {"max_workers": 999}, "supabase": _supabase()}
        )


def test_submit_rejects_missing_supabase():
    with pytest.raises(ValueError, match="supabase"):
        submit_request_from_payload({"options": {"days_back": 1}})


def test_poll_requires_job_id_and_supabase():
    with pytest.raises(ValueError, match="job_id"):
        poll_request_from_payload({"supabase": _supabase()})
    with pytest.raises(ValueError, match="job_id"):
        poll_request_from_payload({"job_id": "abc", "supabase": _supabase()})  # not a uuid
    with pytest.raises(ValueError, match="supabase"):
        poll_request_from_payload(
            {"job_id": "550e8400-e29b-41d4-a716-446655440000"}
        )


def test_poll_rejects_truncated_uuid():
    """Repro of the 22P02 production crash: 7-char first segment instead of 8."""
    with pytest.raises(ValueError, match="UUID"):
        poll_request_from_payload(
            {
                "job_id": "73f4b90-decb-445e-abd9-bc02935d0036",
                "supabase": _supabase(),
            }
        )


def test_worker_requires_job_id_and_supabase():
    with pytest.raises(ValueError):
        worker_request_from_payload({"job_id": ""})
    with pytest.raises(ValueError, match="UUID"):
        worker_request_from_payload({"job_id": "not-a-uuid", "supabase": _supabase()})
    req = worker_request_from_payload(
        {"job_id": "550e8400-e29b-41d4-a716-446655440000", "supabase": _supabase()}
    )
    assert req.job_id == "550e8400-e29b-41d4-a716-446655440000"
