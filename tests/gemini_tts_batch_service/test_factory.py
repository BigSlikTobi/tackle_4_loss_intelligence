"""Validate /submit, /poll, /worker payload parsing for gemini_tts_batch_service."""

from __future__ import annotations

import os

import pytest

from src.functions.gemini_tts_batch_service.core.factory import (
    poll_request_from_payload,
    submit_request_from_payload,
    worker_request_from_payload,
)


@pytest.fixture(autouse=True)
def _supabase_env(monkeypatch):
    """SupabaseConfig is built entirely from env (issue: confused-deputy fix).

    Both URL and key are read from the function's runtime env; callers cannot
    influence them via the request body.
    """
    monkeypatch.setenv("SUPABASE_URL", "https://env.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")


def _supabase() -> dict:
    """Caller-supplied supabase block — should be IGNORED for url/key.

    Kept in payloads only to exercise the legacy field-tolerance path; the
    factory must not honour any url/key here.
    """
    return {"url": "https://attacker.example.com"}


def _create_payload(**overrides) -> dict:
    payload = {
        "action": "create",
        "model_name": "gemini-2.5-pro-preview-tts",
        "voice_name": "Charon",
        "items": [{"id": "story-1", "text": "Hello"}],
        "supabase": _supabase(),
    }
    payload.update(overrides)
    return payload


def test_submit_create_minimal_ok():
    req = submit_request_from_payload(_create_payload())
    assert req.action == "create"
    assert req.create_input.model_name == "gemini-2.5-pro-preview-tts"
    assert req.create_input.voice_name == "Charon"
    assert req.create_input.items == [{"id": "story-1", "text": "Hello"}]
    assert req.supabase.jobs_table == "extraction_jobs"


def test_submit_status_ok():
    req = submit_request_from_payload(
        {"action": "status", "batch_id": "batches/abc", "supabase": _supabase()}
    )
    assert req.action == "status"
    assert req.status_input.batch_id == "batches/abc"


def test_submit_process_with_storage():
    req = submit_request_from_payload(
        {
            "action": "process",
            "batch_id": "batches/abc",
            "storage": {"bucket": "podcasts", "path_prefix": "weekly"},
            "supabase": _supabase(),
        }
    )
    assert req.action == "process"
    assert req.process_input.bucket == "podcasts"
    assert req.process_input.path_prefix == "weekly"


def test_submit_process_storage_defaults():
    req = submit_request_from_payload(
        {"action": "process", "batch_id": "batches/abc", "supabase": _supabase()}
    )
    assert req.process_input.bucket == "audio"
    assert req.process_input.path_prefix == "gemini-tts-batch"


def test_submit_rejects_invalid_action():
    with pytest.raises(ValueError, match="action must be one of"):
        submit_request_from_payload(
            {"action": "delete", "supabase": _supabase()}
        )


def test_submit_rejects_missing_action():
    with pytest.raises(ValueError, match="action must be one of"):
        submit_request_from_payload({"supabase": _supabase()})


def test_submit_create_rejects_empty_items():
    with pytest.raises(ValueError, match="items must be a non-empty list"):
        submit_request_from_payload(_create_payload(items=[]))


def test_submit_create_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="duplicate item id"):
        submit_request_from_payload(
            _create_payload(items=[{"id": "x", "text": "a"}, {"id": "x", "text": "b"}])
        )


def test_submit_create_rejects_missing_id():
    with pytest.raises(ValueError, match="non-empty string id"):
        submit_request_from_payload(
            _create_payload(items=[{"text": "no id"}])
        )


def test_submit_create_rejects_missing_model():
    with pytest.raises(ValueError, match="model_name is required"):
        submit_request_from_payload(_create_payload(model_name=""))


def test_submit_status_rejects_missing_batch_id():
    with pytest.raises(ValueError, match="batch_id is required"):
        submit_request_from_payload({"action": "status", "supabase": _supabase()})


def test_submit_process_rejects_missing_batch_id():
    with pytest.raises(ValueError, match="batch_id is required"):
        submit_request_from_payload({"action": "process", "supabase": _supabase()})


def test_submit_accepts_request_without_supabase_block():
    """No payload supabase block is fine — config comes from env."""
    req = submit_request_from_payload(
        {
            "action": "create",
            "model_name": "m",
            "items": [{"id": "a", "text": "t"}],
        }
    )
    assert req.supabase.url == "https://env.supabase.co"
    assert req.supabase.key == "test-key"


def test_submit_pins_url_to_env_ignoring_caller_supplied_url():
    """Confused-deputy fix: caller-supplied supabase.url MUST be ignored."""
    req = submit_request_from_payload(_create_payload())
    # _supabase() sends https://attacker.example.com — must not propagate.
    assert req.supabase.url == "https://env.supabase.co"
    assert req.supabase.key == "test-key"


def test_submit_rejects_when_supabase_url_env_unset(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        submit_request_from_payload(_create_payload())


def test_submit_rejects_when_service_role_key_env_unset(monkeypatch):
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    with pytest.raises(ValueError, match="SUPABASE_SERVICE_ROLE_KEY"):
        submit_request_from_payload(_create_payload())


def test_poll_requires_job_id():
    with pytest.raises(ValueError, match="job_id is required"):
        poll_request_from_payload({"supabase": _supabase()})


def test_poll_uses_env_supabase_when_payload_block_missing():
    req = poll_request_from_payload({"job_id": "abc"})
    assert req.supabase.url == "https://env.supabase.co"


def test_poll_rejects_when_supabase_env_unset(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        poll_request_from_payload({"job_id": "abc"})


def test_worker_requires_job_id():
    with pytest.raises(ValueError, match="job_id is required"):
        worker_request_from_payload({"job_id": ""})


def test_worker_pins_url_to_env_ignoring_caller_supplied_url():
    req = worker_request_from_payload({"job_id": "abc", "supabase": _supabase()})
    assert req.job_id == "abc"
    assert req.supabase.url == "https://env.supabase.co"
