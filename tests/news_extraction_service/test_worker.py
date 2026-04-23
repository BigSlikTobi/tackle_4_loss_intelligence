"""job_runner tests with a fake JobStore + fake pipeline (no network)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from src.shared.jobs.contracts import SupabaseConfig
from src.functions.news_extraction_service.core.config import ExtractionOptions
from src.functions.news_extraction_service.core.worker.job_runner import (
    SERVICE_NAME,
    _days_back_for_since,
    _filter_records_since,
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


class _FakePipeline:
    """In-memory stand-in for NewsExtractionPipeline."""

    def __init__(self, raw: Dict[str, Any]):
        self.closed = False
        self.extract_kwargs: Dict[str, Any] = {}
        self._raw = raw

    def extract(self, **kwargs):
        self.extract_kwargs = kwargs
        return self._raw

    def close(self):
        self.closed = True


def _supabase() -> SupabaseConfig:
    return SupabaseConfig(url="u", key="k")


def _queued_row(options: Optional[Dict[str, Any]] = None):
    return {
        "job_id": str(uuid4()),
        "status": "queued",
        "input": {"options": options or {}},
    }


def _ok_pipeline_factory(raw: Dict[str, Any]):
    pipeline = _FakePipeline(raw)
    return pipeline, lambda *_args, **_kwargs: pipeline


def test_run_job_succeeds_and_returns_items():
    items = [
        {
            "url": "https://example.com/a",
            "title": "A",
            "publication_date": "2026-04-22T10:00:00+00:00",
            "source_name": "ESPN - NFL News",
            "publisher": "ESPN",
        },
        {
            "url": "https://example.com/b",
            "title": "B",
            "publication_date": "2026-04-22T10:30:00+00:00",
            "source_name": "ESPN - NFL News",
            "publisher": "ESPN",
        },
    ]
    raw = {
        "success": True,
        "sources_processed": 1,
        "items_extracted": 2,
        "items_filtered": 0,
        "records": items,
        "metrics": {"k": 1},
        "performance": {"duration_seconds": 4.2},
    }
    pipeline, factory = _ok_pipeline_factory(raw)
    row = _queued_row({"source_filter": "ESPN"})
    store = _FakeStore(row)
    summary = run_job(
        row["job_id"], _supabase(), pipeline_factory=factory, store=store
    )
    assert summary["status"] == "succeeded"
    assert summary["sources_processed"] == 1
    assert summary["items_count"] == 2
    assert store.terminal is not None
    assert store.terminal["items"] == items
    assert store.terminal["items_count"] == 2
    assert pipeline.closed is True


def test_run_job_post_filters_records_by_since():
    """Worker drops records older than `since` even if the pipeline returned them."""
    items = [
        {"url": "old", "publication_date": "2026-04-20T10:00:00+00:00"},
        {"url": "boundary", "publication_date": "2026-04-22T10:00:00+00:00"},
        {"url": "new", "publication_date": "2026-04-22T11:00:00+00:00"},
        {"url": "no-date"},  # no publication_date — should be dropped when since is set
    ]
    raw = {"success": True, "records": items, "items_extracted": 4}
    _, factory = _ok_pipeline_factory(raw)
    row = _queued_row({"source_filter": "ESPN", "since": "2026-04-22T10:00:00+00:00"})
    store = _FakeStore(row)
    run_job(row["job_id"], _supabase(), pipeline_factory=factory, store=store)
    urls = [item["url"] for item in store.terminal["items"]]
    assert urls == ["boundary", "new"]
    assert store.terminal["items_count"] == 2


def test_run_job_keeps_dateless_records_when_since_unset():
    """When `since` is None we never drop records over a missing date."""
    items = [
        {"url": "a", "publication_date": "2026-04-22T10:00:00+00:00"},
        {"url": "no-date"},
    ]
    raw = {"success": True, "records": items, "items_extracted": 2}
    _, factory = _ok_pipeline_factory(raw)
    row = _queued_row({"source_filter": "ESPN"})
    store = _FakeStore(row)
    run_job(row["job_id"], _supabase(), pipeline_factory=factory, store=store)
    assert store.terminal["items_count"] == 2


def test_days_back_for_since_helper():
    now = datetime.now(timezone.utc)
    assert _days_back_for_since(None) is None
    # ~3 days ago → at least 4 (3 + 1 buffer)
    days = _days_back_for_since(now - timedelta(days=3, hours=2))
    assert days >= 4
    # Sub-day window still gets at least 1.
    assert _days_back_for_since(now - timedelta(minutes=5)) >= 1


def test_filter_records_since_handles_z_suffix():
    """The post-filter accepts Z-suffixed ISO dates from the transformer."""
    items = [
        {"url": "a", "publication_date": "2026-04-22T10:00:00Z"},
        {"url": "b", "publication_date": "2026-04-21T10:00:00Z"},
    ]
    cutoff = datetime(2026, 4, 22, 0, 0, 0, tzinfo=timezone.utc)
    kept = _filter_records_since(items, cutoff)
    assert [r["url"] for r in kept] == ["a"]


def test_run_job_forces_dry_run_true_so_pipeline_never_writes():
    """Worker MUST call extract(dry_run=True) regardless of stored options.

    This is the load-bearing guarantee that the service stays stateless —
    if a future caller smuggles dry_run=False into the stored input, the
    worker still overrides it.
    """
    raw = {"success": True, "records": []}
    pipeline, factory = _ok_pipeline_factory(raw)
    # Simulate a stored payload that (incorrectly) carries dry_run=False.
    row = _queued_row({"source_filter": "ESPN"})
    row["input"]["options"]["dry_run"] = False
    row["input"]["options"]["clear"] = True
    store = _FakeStore(row)
    run_job(row["job_id"], _supabase(), pipeline_factory=factory, store=store)
    assert pipeline.extract_kwargs["dry_run"] is True
    assert pipeline.extract_kwargs["clear"] is False


def test_null_watermark_store_returns_empty_and_swallows_updates():
    """The injected watermark store must short-circuit reads + writes."""
    from src.functions.news_extraction_service.core.worker.job_runner import (
        _NullWatermarkStore,
    )

    store = _NullWatermarkStore()
    assert store.fetch_watermarks() == {}
    # Update is a no-op (no exception, no return value).
    assert store.update_watermarks({"src": "anything"}) is None


def test_run_job_marks_failed_on_pipeline_success_false():
    raw = {"success": False, "errors": ["config load failed"]}
    _, factory = _ok_pipeline_factory(raw)
    row = _queued_row()
    store = _FakeStore(row)
    summary = run_job(row["job_id"], _supabase(), pipeline_factory=factory, store=store)
    assert summary["status"] == "failed"
    assert summary["reason"] == "pipeline_failure"
    assert store.error["code"] == "pipeline_failure"
    assert "config load failed" in store.error["message"]


def test_run_job_marks_failed_on_pipeline_exception():
    def factory(_supabase, _options):
        class _Boom(_FakePipeline):
            def extract(self, **kwargs):
                raise RuntimeError("network down")

        return _Boom({})

    row = _queued_row()
    store = _FakeStore(row)
    summary = run_job(row["job_id"], _supabase(), pipeline_factory=factory, store=store)
    assert summary["status"] == "failed"
    assert summary["reason"] == "exception"
    assert store.error["code"] == "RuntimeError"
    assert store.error["message"] == "network down"


def test_run_job_no_op_when_already_terminal():
    row = {"job_id": "abc", "status": "succeeded", "input": {"options": {}}}
    store = _FakeStore(row)
    _, factory = _ok_pipeline_factory({})
    summary = run_job("abc", _supabase(), pipeline_factory=factory, store=store)
    assert summary["status"] == "succeeded"
    assert summary.get("idempotent_skip") is True
    assert store.terminal is None


def test_run_job_returns_not_found_when_row_missing():
    store = _FakeStore(None)
    _, factory = _ok_pipeline_factory({})
    summary = run_job("missing", _supabase(), pipeline_factory=factory, store=store)
    assert summary["status"] == "not_found"


def test_run_job_marks_failed_on_invalid_input():
    """Stored options re-validated on rehydrate; future `since` is rejected."""
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    row = {"job_id": "abc", "status": "queued", "input": {"options": {"since": future}}}
    store = _FakeStore(row)
    _, factory = _ok_pipeline_factory({})
    summary = run_job("abc", _supabase(), pipeline_factory=factory, store=store)
    assert summary["status"] == "failed"
    assert summary["reason"] == "invalid_input"
    assert store.error["code"] == "invalid_input"


def test_service_name_constant():
    assert SERVICE_NAME == "news_extraction"
