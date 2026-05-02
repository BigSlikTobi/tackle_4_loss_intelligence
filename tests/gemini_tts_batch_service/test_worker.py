"""Worker job_runner tests with fake JobStore + injected dispatch fn.

The injected ``dispatch_fn`` seam keeps these tests dependency-free — no
google-genai, pydub, or supabase imports are exercised.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import pytest

from src.shared.jobs.contracts import SupabaseConfig
from src.functions.gemini_tts_batch_service.core.worker.job_runner import (
    SERVICE_NAME,
    run_job,
)


class _FakeStore:
    def __init__(self, row: Optional[Dict[str, Any]]):
        self._row = row
        self.terminal: Optional[Dict[str, Any]] = None
        self.error: Optional[Dict[str, Any]] = None
        self.claimed = False

    def peek(self, job_id: str):
        return self._row

    def mark_running(self, job_id: str):
        if self._row and self._row.get("status") == "queued":
            self._row["status"] = "running"
            self.claimed = True
            return self._row
        return None

    def mark_succeeded(self, job_id: str, result: Dict[str, Any]):
        self.terminal = result

    def mark_failed(self, job_id: str, error: Dict[str, Any]):
        self.error = error


def _supabase() -> SupabaseConfig:
    return SupabaseConfig(url="u", key="k")


def _queued_row(action: str, **input_overrides) -> Dict[str, Any]:
    base: Dict[str, Any] = {"action": action}
    if action == "create":
        base.update(
            {
                "model_name": "gemini-2.5-pro-preview-tts",
                "voice_name": "Charon",
                "items": [{"id": "story-1", "text": "Hello world"}],
            }
        )
    elif action == "status":
        base.update({"batch_id": "batches/abc"})
    elif action == "process":
        base.update(
            {
                "batch_id": "batches/abc",
                "bucket": "audio",
                "path_prefix": "gemini-tts-batch",
            }
        )
    base.update(input_overrides)
    return {
        "job_id": str(uuid4()),
        "status": "queued",
        "input": base,
    }


def _record_dispatch(payload: Dict[str, Any]):
    """Build a dispatch_fn that records calls and returns the given payload."""
    calls: List[Tuple[str, Dict[str, Any]]] = []

    def _fn(action: str, input_payload: Dict[str, Any]) -> Dict[str, Any]:
        calls.append((action, input_payload))
        return payload

    return _fn, calls


@pytest.fixture(autouse=True)
def _storage_env(monkeypatch):
    """The process action's _validate_input reads STORAGE_SUPABASE_* from env."""
    monkeypatch.setenv("STORAGE_SUPABASE_URL", "https://storage.supabase.co")
    monkeypatch.setenv("STORAGE_SUPABASE_KEY", "storage-key")


def test_run_job_create_dispatches_and_persists():
    row = _queued_row("create")
    store = _FakeStore(row)
    dispatch, calls = _record_dispatch(
        {"batch_id": "batches/xyz", "status": "JOB_STATE_QUEUED"}
    )

    summary = run_job(row["job_id"], _supabase(), store=store, dispatch_fn=dispatch)

    assert summary["status"] == "succeeded"
    assert summary["action"] == "create"
    assert store.claimed is True
    assert store.terminal["action"] == "create"
    assert store.terminal["batch_id"] == "batches/xyz"
    assert calls[0][0] == "create"
    assert calls[0][1]["model_name"] == "gemini-2.5-pro-preview-tts"


def test_run_job_status_dispatches():
    row = _queued_row("status")
    store = _FakeStore(row)
    dispatch, _ = _record_dispatch({"status": "JOB_STATE_RUNNING"})
    summary = run_job(row["job_id"], _supabase(), store=store, dispatch_fn=dispatch)
    assert summary["status"] == "succeeded"
    assert store.terminal["action"] == "status"


def test_run_job_process_dispatches():
    row = _queued_row("process")
    store = _FakeStore(row)
    dispatch, calls = _record_dispatch(
        {"processed_count": 2, "failed_count": 0, "items": []}
    )
    summary = run_job(row["job_id"], _supabase(), store=store, dispatch_fn=dispatch)
    assert summary["status"] == "succeeded"
    assert store.terminal["action"] == "process"
    assert store.terminal["processed_count"] == 2
    # Caller-chosen bucket/prefix flow through to dispatch.
    assert calls[0][1]["bucket"] == "audio"
    assert calls[0][1]["path_prefix"] == "gemini-tts-batch"


def test_run_job_process_fails_when_storage_env_missing(monkeypatch):
    monkeypatch.delenv("STORAGE_SUPABASE_URL", raising=False)
    monkeypatch.delenv("STORAGE_SUPABASE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    row = _queued_row("process")
    store = _FakeStore(row)
    dispatch, _ = _record_dispatch({})
    summary = run_job(row["job_id"], _supabase(), store=store, dispatch_fn=dispatch)
    assert summary["status"] == "failed"
    assert summary["reason"] == "invalid_input"
    assert "Storage credentials not configured" in store.error["message"]


def test_run_job_no_op_when_already_terminal():
    row = {
        "job_id": "abc",
        "status": "succeeded",
        "input": {"action": "status", "batch_id": "x"},
    }
    store = _FakeStore(row)
    dispatch, _ = _record_dispatch({})
    summary = run_job("abc", _supabase(), store=store, dispatch_fn=dispatch)
    assert summary["status"] == "succeeded"
    assert summary.get("idempotent_skip") is True
    assert store.terminal is None


def test_run_job_returns_not_found_when_row_missing():
    store = _FakeStore(None)
    dispatch, _ = _record_dispatch({})
    summary = run_job("missing", _supabase(), store=store, dispatch_fn=dispatch)
    assert summary["status"] == "not_found"


def test_run_job_marks_failed_on_invalid_action():
    row = {"job_id": "abc", "status": "queued", "input": {"action": "delete"}}
    store = _FakeStore(row)
    dispatch, _ = _record_dispatch({})
    summary = run_job("abc", _supabase(), store=store, dispatch_fn=dispatch)
    assert summary["status"] == "failed"
    assert summary["reason"] == "invalid_input"
    assert store.error["code"] == "invalid_input"


def test_run_job_marks_failed_on_value_error_from_dispatch():
    row = _queued_row("create")
    store = _FakeStore(row)

    def boom(action, payload):
        raise ValueError("model does not support batchGenerateContent")

    summary = run_job(row["job_id"], _supabase(), store=store, dispatch_fn=boom)
    assert summary["status"] == "failed"
    assert summary["reason"] == "validation_error"
    assert store.error["retryable"] is False


def test_run_job_marks_failed_retryable_on_runtime_error():
    row = _queued_row("status")
    store = _FakeStore(row)

    def boom(action, payload):
        raise RuntimeError("upstream Gemini 503")

    summary = run_job(row["job_id"], _supabase(), store=store, dispatch_fn=boom)
    assert summary["status"] == "failed"
    assert summary["reason"] == "upstream_error"
    assert store.error["retryable"] is True


def test_service_name_is_gemini_tts_batch():
    assert SERVICE_NAME == "gemini_tts_batch"
