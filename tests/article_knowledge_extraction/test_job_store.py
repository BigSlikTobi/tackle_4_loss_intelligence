"""Exercise JobStore against an in-memory fake Supabase client."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import pytest

from src.functions.article_knowledge_extraction.core.config import SupabaseConfig
from src.functions.article_knowledge_extraction.core.db.job_store import JobStore


# A small mock of the relevant Supabase client surface. Supports the exact
# chained calls JobStore uses: .table().insert/update/select/delete/range/lt/eq/
# single/limit/execute(), and .rpc().execute().


class _Response:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, store: "_FakeTable"):
        self._store = store
        self._filters: List[tuple] = []
        self._select_fields: Optional[str] = None
        self._update_patch: Optional[Dict[str, Any]] = None
        self._insert_row: Optional[Dict[str, Any]] = None
        self._is_delete = False
        self._single = False
        self._limit: Optional[int] = None

    # builders
    def select(self, fields: str) -> "_Query":
        self._select_fields = fields
        return self

    def insert(self, row: Dict[str, Any]) -> "_Query":
        self._insert_row = row
        return self

    def update(self, patch: Dict[str, Any]) -> "_Query":
        self._update_patch = patch
        return self

    def delete(self) -> "_Query":
        self._is_delete = True
        return self

    def eq(self, field: str, value: Any) -> "_Query":
        self._filters.append(("eq", field, value))
        return self

    def lt(self, field: str, value: Any) -> "_Query":
        self._filters.append(("lt", field, value))
        return self

    def single(self) -> "_Query":
        self._single = True
        return self

    def limit(self, n: int) -> "_Query":
        self._limit = n
        return self

    def range(self, start: int, end: int) -> "_Query":  # pragma: no cover - not used
        self._limit = end - start + 1
        return self

    def execute(self) -> _Response:
        rows = self._store.rows

        def _matches(row):
            for op, field, value in self._filters:
                if op == "eq":
                    if row.get(field) != value:
                        return False
                elif op == "lt":
                    a = row.get(field)
                    if a is None or not (a < value):
                        return False
            return True

        if self._insert_row is not None:
            new_row = dict(self._insert_row)
            new_row.setdefault("job_id", str(uuid4()))
            new_row.setdefault("attempts", 0)
            now = datetime.now(timezone.utc).isoformat()
            new_row.setdefault("created_at", now)
            new_row.setdefault("updated_at", now)
            new_row.setdefault("expires_at", (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat())
            rows.append(new_row)
            return _Response([new_row])

        if self._is_delete:
            kept, removed = [], []
            for row in rows:
                (removed if _matches(row) else kept).append(row)
            self._store.rows = kept
            return _Response(removed)

        if self._update_patch is not None:
            updated = []
            for row in rows:
                if _matches(row):
                    row.update(self._update_patch)
                    updated.append(row)
            return _Response(updated)

        # Select
        matched = [row for row in rows if _matches(row)]
        if self._limit is not None:
            matched = matched[: self._limit]
        if self._single:
            return _Response(matched[0] if matched else None)
        return _Response(matched)


class _FakeTable:
    def __init__(self, rows: List[Dict[str, Any]]):
        self.rows = rows


class _FakeClient:
    def __init__(self):
        self._tables: Dict[str, _FakeTable] = {}
        self.consumed_ids: List[str] = []

    def table(self, name: str) -> _Query:
        table = self._tables.setdefault(name, _FakeTable([]))
        return _Query(table)

    def rpc(self, name: str, params: Dict[str, Any]):
        assert name == "consume_article_knowledge_job"
        job_id = params["p_job_id"]
        # Emulate the Postgres function: delete if terminal, return row
        for table in self._tables.values():
            for idx, row in enumerate(table.rows):
                if row.get("job_id") == job_id and row.get("status") in (
                    "succeeded",
                    "failed",
                ):
                    del table.rows[idx]
                    self.consumed_ids.append(job_id)
                    return _RpcExecutor([row])
        return _RpcExecutor([])


class _RpcExecutor:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return _Response(self._data)


@pytest.fixture
def store() -> JobStore:
    client = _FakeClient()
    config = SupabaseConfig(url="u", key="k")
    return JobStore(config, client=client)


def test_create_mark_running_mark_succeeded_and_consume(store: JobStore):
    job = store.create_job({"article": {"text": "t"}})
    job_id = job["job_id"]
    assert job["status"] == "queued"

    claimed = store.mark_running(job_id)
    assert claimed is not None
    assert claimed["status"] == "running"
    # mark_running should only succeed once
    assert store.mark_running(job_id) is None

    peek = store.peek(job_id)
    assert peek["attempts"] == 1

    store.mark_succeeded(job_id, {"ok": True})
    assert store.peek(job_id)["status"] == "succeeded"

    consumed = store.consume_terminal(job_id)
    assert consumed is not None
    assert consumed["status"] == "succeeded"
    assert consumed["result"] == {"ok": True}

    # After consume, the row is gone — peek returns None, second consume returns None
    assert store.peek(job_id) is None
    assert store.consume_terminal(job_id) is None


def test_mark_failed_flows_through_consume(store: JobStore):
    job = store.create_job({"article": {"text": "t"}})
    job_id = job["job_id"]
    store.mark_running(job_id)
    store.mark_failed(job_id, {"code": "X", "message": "boom", "retryable": False})

    consumed = store.consume_terminal(job_id)
    assert consumed["status"] == "failed"
    assert consumed["error"]["message"] == "boom"


def test_consume_non_terminal_returns_none(store: JobStore):
    job = store.create_job({"article": {"text": "t"}})
    assert store.consume_terminal(job["job_id"]) is None


def test_delete_expired_removes_past_rows(store: JobStore):
    job = store.create_job({"article": {"text": "t"}})
    # Force expiry in the past
    rows = store._client._tables["article_knowledge_extraction_jobs"].rows
    rows[0]["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat()

    deleted = store.delete_expired()
    assert deleted == 1
    assert store.peek(job["job_id"]) is None
