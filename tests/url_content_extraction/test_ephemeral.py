"""Tests for the ephemeral content handoff (Phase 6a).

Covers:
- ``EphemeralContentWriter.upsert_content`` skips invalid rows, applies TTL,
  and chunks correctly.
- ``EphemeralContentWriter.mark_consumed`` filters previously-consumed rows.
- ``EphemeralContentReader.fetch_content`` returns ``None`` on miss/expiry.
- ``handle_request`` enforces the ``WORKER_TOKEN`` shared secret when set
  and bypasses auth when unset (local dev).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from src.functions.url_content_extraction.core.db.ephemeral import (
    EphemeralContentReader,
    EphemeralContentWriter,
    TABLE_NAME,
)


# ---------------------------------------------------------------------------
# Fake Supabase client (records calls + returns canned data)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _FakeQuery:
    """Minimal chainable query stub. Records the final call into ``log``."""

    def __init__(self, table: str, log: List[Dict[str, Any]], canned: Dict[str, Any]) -> None:
        self._table = table
        self._log = log
        self._canned = canned
        self._call: Dict[str, Any] = {"table": table}

    def _record_terminal(self, op: str, payload: Any = None) -> "_FakeQuery":
        self._call["op"] = op
        if payload is not None:
            self._call["payload"] = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self._call["on_conflict"] = on_conflict
        return self._record_terminal("upsert", payload)

    def update(self, payload):
        return self._record_terminal("update", payload)

    def delete(self):
        return self._record_terminal("delete")

    def select(self, cols):
        self._call.setdefault("op", "select")
        self._call["cols"] = cols
        return self

    def in_(self, col, vals):
        self._call.setdefault("filters", []).append(("in", col, list(vals)))
        return self

    def eq(self, col, val):
        self._call.setdefault("filters", []).append(("eq", col, val))
        return self

    def gt(self, col, val):
        self._call.setdefault("filters", []).append(("gt", col, val))
        return self

    def is_(self, col, val):
        self._call.setdefault("filters", []).append(("is", col, val))
        return self

    def or_(self, expr):
        self._call.setdefault("filters", []).append(("or", expr))
        return self

    def order(self, col, desc=False):
        self._call["order"] = (col, desc)
        return self

    def limit(self, n):
        self._call["limit"] = n
        return self

    def range(self, lo, hi):
        self._call["range"] = (lo, hi)
        return self

    def execute(self):
        self._log.append(self._call)
        # Canned response keyed by op.
        op = self._call.get("op", "")
        return _FakeResponse(self._canned.get(op, []))


class FakeClient:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        # Per-op canned data; tests override before calling.
        self.canned: Dict[str, Any] = {
            "upsert": [],
            "update": [],
            "delete": [],
            "select": [],
        }

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(name, self.calls, self.canned)


# ---------------------------------------------------------------------------
# Writer tests
# ---------------------------------------------------------------------------


def test_upsert_skips_rows_missing_required_fields():
    client = FakeClient()
    writer = EphemeralContentWriter(client)
    written = writer.upsert_content(
        [
            {"news_url_id": "a", "content": "hello"},
            {"news_url_id": "", "content": "x"},  # invalid
            {"news_url_id": "b"},  # missing content
        ],
        # No canned response → 0 rows back, but we assert call shape directly.
    )
    assert written == 0  # canned upsert returns []
    upserts = [c for c in client.calls if c.get("op") == "upsert"]
    assert len(upserts) == 1
    rows = upserts[0]["payload"]
    assert [r["news_url_id"] for r in rows] == ["a"]
    assert upserts[0]["on_conflict"] == "news_url_id"
    # TTL fields populated.
    assert rows[0]["expires_at"] > rows[0]["extracted_at"]


def test_upsert_chunks_large_payloads():
    client = FakeClient()
    client.canned["upsert"] = [{"id": "x"}]  # any non-empty
    writer = EphemeralContentWriter(client)
    rows = [
        {"news_url_id": f"id-{i}", "content": f"c-{i}"} for i in range(250)
    ]
    writer.upsert_content(rows, chunk_size=100)
    upserts = [c for c in client.calls if c.get("op") == "upsert"]
    assert [len(c["payload"]) for c in upserts] == [100, 100, 50]


def test_mark_consumed_filters_previously_consumed():
    client = FakeClient()
    client.canned["update"] = [{"id": "x"}]
    writer = EphemeralContentWriter(client)
    writer.mark_consumed(["a", "b"])
    update = next(c for c in client.calls if c.get("op") == "update")
    filters = dict((f[1], f) for f in update["filters"])
    # Must restrict to consumed_at IS NULL so we don't re-stamp finished rows.
    assert filters["consumed_at"] == ("is", "consumed_at", "null")
    assert filters["news_url_id"][2] == ["a", "b"]


# ---------------------------------------------------------------------------
# Reader tests
# ---------------------------------------------------------------------------


def test_fetch_content_returns_none_when_no_row():
    client = FakeClient()
    client.canned["select"] = []
    reader = EphemeralContentReader(client)
    assert reader.fetch_content("missing") is None


def test_fetch_content_returns_string_when_present():
    client = FakeClient()
    client.canned["select"] = [{"content": "hello world"}]
    reader = EphemeralContentReader(client)
    assert reader.fetch_content("present") == "hello world"
    select = next(c for c in client.calls if c.get("op") == "select")
    # Filter on freshness (gt expires_at) and ID match.
    filter_cols = [f[1] for f in select["filters"]]
    assert "expires_at" in filter_cols
    assert "news_url_id" in filter_cols


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


def test_authenticate_bypasses_when_token_unset(monkeypatch):
    from src.functions.url_content_extraction.functions.main import authenticate

    monkeypatch.delenv("WORKER_TOKEN", raising=False)
    assert authenticate({}) is None
    assert authenticate(None) is None


def test_authenticate_rejects_missing_header(monkeypatch):
    from src.functions.url_content_extraction.functions.main import authenticate

    monkeypatch.setenv("WORKER_TOKEN", "secret")
    err = authenticate({})
    assert err is not None
    assert err["status_code"] == 401


def test_authenticate_rejects_wrong_token(monkeypatch):
    from src.functions.url_content_extraction.functions.main import authenticate

    monkeypatch.setenv("WORKER_TOKEN", "secret")
    err = authenticate({"X-Worker-Token": "wrong"})
    assert err is not None
    assert err["status_code"] == 401


def test_authenticate_accepts_correct_token(monkeypatch):
    from src.functions.url_content_extraction.functions.main import authenticate

    monkeypatch.setenv("WORKER_TOKEN", "secret")
    assert authenticate({"X-Worker-Token": "secret"}) is None


def test_authenticate_case_insensitive_dict_lookup(monkeypatch):
    from src.functions.url_content_extraction.functions.main import authenticate

    monkeypatch.setenv("WORKER_TOKEN", "secret")
    # Plain dict with lowercase key — should still be accepted.
    assert authenticate({"x-worker-token": "secret"}) is None


def test_handle_request_returns_401_when_token_invalid(monkeypatch):
    from src.functions.url_content_extraction.functions.main import handle_request

    monkeypatch.setenv("WORKER_TOKEN", "secret")
    result = handle_request({"urls": ["https://example.com"]}, headers={})
    assert result["status"] == "error"
    assert result["status_code"] == 401
