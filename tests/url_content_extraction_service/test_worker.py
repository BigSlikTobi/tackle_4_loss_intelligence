"""Worker job_runner tests with fake JobStore + fake extractor (no network)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from src.shared.contracts.extracted_content import (
    ExtractedContent,
    ExtractionMetadata,
)
from src.shared.jobs.contracts import SupabaseConfig
from src.functions.url_content_extraction_service.core.worker.job_runner import (
    SERVICE_NAME,
    run_job,
)


class _FakeStore:
    """In-memory stand-in for JobStore."""

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


def _queued_row(urls):
    return {
        "job_id": str(uuid4()),
        "status": "queued",
        "input": {"urls": urls, "options": {}},
    }


def _ok_extractor(url: str, options) -> ExtractedContent:
    return ExtractedContent(
        url=url,
        title="t",
        paragraphs=["paragraph one", "paragraph two"],
        metadata=ExtractionMetadata(
            fetched_at=datetime.now(timezone.utc),
            extractor="fake",
            duration_seconds=0.1,
        ),
    )


def _bad_extractor(url: str, options) -> ExtractedContent:
    return ExtractedContent(url=url, error="boom")


def test_run_job_succeeds_and_persists_articles():
    row = _queued_row(["https://example.com/a", "https://example.com/b"])
    store = _FakeStore(row)
    summary = run_job(row["job_id"], _supabase(), extractor_fn=_ok_extractor, store=store)
    assert summary["status"] == "succeeded"
    assert summary["total"] == 2
    assert summary["succeeded"] == 2
    assert store.claimed is True
    assert store.terminal is not None
    articles = store.terminal["articles"]
    assert len(articles) == 2
    assert all("error" not in a for a in articles)
    assert articles[0]["content"].startswith("paragraph one")


def test_run_job_records_per_url_failures_without_aborting():
    row = _queued_row(["https://good", "https://bad"])
    store = _FakeStore(row)

    def mixed(url, options):
        return _ok_extractor(url, options) if "good" in url else _bad_extractor(url, options)

    summary = run_job(row["job_id"], _supabase(), extractor_fn=mixed, store=store)
    assert summary["status"] == "succeeded"
    assert summary["total"] == 2
    assert summary["succeeded"] == 1
    articles = store.terminal["articles"]
    assert articles[1]["error"] == "boom"


def test_run_job_no_op_when_already_terminal():
    row = {"job_id": "abc", "status": "succeeded", "input": {"urls": ["x"]}}
    store = _FakeStore(row)
    summary = run_job("abc", _supabase(), extractor_fn=_ok_extractor, store=store)
    assert summary["status"] == "succeeded"
    assert summary.get("idempotent_skip") is True
    assert store.terminal is None


def test_run_job_returns_not_found_when_row_missing():
    store = _FakeStore(None)
    summary = run_job("missing", _supabase(), extractor_fn=_ok_extractor, store=store)
    assert summary["status"] == "not_found"


def test_run_job_marks_failed_on_invalid_input():
    row = {"job_id": "abc", "status": "queued", "input": {"urls": []}}
    store = _FakeStore(row)
    summary = run_job("abc", _supabase(), extractor_fn=_ok_extractor, store=store)
    assert summary["status"] == "failed"
    assert summary["reason"] == "invalid_input"
    assert store.error["code"] == "invalid_input"


def test_service_name_is_url_content_extraction():
    assert SERVICE_NAME == "url_content_extraction"
