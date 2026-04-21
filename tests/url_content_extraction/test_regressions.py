"""Regression tests for url_content_extraction Phase A/B fixes.

Covers:
- `_build_options` merge precedence (base < base.options < metadata <
  metadata.options), previously inverted so top-level `base` overrode the
  nested `options` blocks.
- `filter_story_facts` is now the single source of truth shared between
  realtime and batch paths.
- `FACT_PROMPT_VERSION` + `get_formatted_prompt` are re-exported from the
  realtime post-processor via shared module.
- `is_heavy_url` is the single source for Playwright-required hosts.
- `handle_request` basics: rejects empty/invalid input, preserves metadata,
  routes extractors, reports per-URL errors without aborting the batch.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest


# ---------------------------------------------------------------------------
# _build_options precedence
# ---------------------------------------------------------------------------


def test_build_options_metadata_options_beats_everything():
    from src.functions.url_content_extraction.functions.main import _build_options

    base = {
        "foo": "base-top",
        "options": {"foo": "base-nested"},
    }
    metadata = {
        "foo": "meta-top",
        "options": {"foo": "meta-nested"},
    }
    result = _build_options(metadata, base)
    assert result["foo"] == "meta-nested"


def test_build_options_metadata_top_beats_base_options():
    from src.functions.url_content_extraction.functions.main import _build_options

    base = {
        "foo": "base-top",
        "options": {"foo": "base-nested"},
    }
    metadata = {"foo": "meta-top"}
    result = _build_options(metadata, base)
    assert result["foo"] == "meta-top"


def test_build_options_base_options_beats_base_top():
    from src.functions.url_content_extraction.functions.main import _build_options

    base = {
        "foo": "base-top",
        "options": {"foo": "base-nested"},
    }
    metadata: Dict[str, Any] = {}
    result = _build_options(metadata, base)
    assert result["foo"] == "base-nested"


def test_build_options_drops_nested_options_key():
    """The flattened result should not carry the raw nested `options` map."""
    from src.functions.url_content_extraction.functions.main import _build_options

    result = _build_options({"options": {"x": 1}}, {})
    assert "options" not in result
    assert result["x"] == 1


# ---------------------------------------------------------------------------
# Shared fact prompt + filter (2.3 / 2.4)
# ---------------------------------------------------------------------------


def test_writer_defaults_to_canonical_prompt_version():
    """FactsWriter must default to the canonical FACT_PROMPT_VERSION so the
    realtime and batch paths (and any future caller) can't drift."""
    from src.functions.url_content_extraction.core.db import FactsWriter
    from src.functions.url_content_extraction.core.facts.prompts import (
        FACT_PROMPT_VERSION as canonical,
    )

    writer = FactsWriter(client=object())
    assert writer.prompt_version == canonical


def test_filter_story_facts_rejects_author_bio_and_keeps_story():
    from src.functions.url_content_extraction.core.facts.filter import (
        filter_story_facts,
    )

    facts = [
        "Joe Burrow threw for 350 yards against the Ravens on Sunday.",
        "Adam Schefter is a senior reporter for ESPN.",
        "Follow us on Twitter for the latest updates.",
        "The Bengals signed Tee Higgins to a four-year extension.",
    ]
    valid, rejected = filter_story_facts(facts)
    assert "Joe Burrow threw for 350 yards against the Ravens on Sunday." in valid
    assert "The Bengals signed Tee Higgins to a four-year extension." in valid
    # Both filter paths reject these author / boilerplate entries.
    assert any("Schefter" in r for r in rejected)
    assert any("Twitter" in r for r in rejected)


# ---------------------------------------------------------------------------
# is_heavy_url / single source (2.5)
# ---------------------------------------------------------------------------


def test_is_heavy_url_matches_known_playwright_host():
    from src.functions.url_content_extraction.core.extractors.extractor_factory import (
        is_heavy_url,
    )

    assert is_heavy_url("https://www.espn.com/nfl/story/_/id/123")
    assert not is_heavy_url("https://apnews.com/nfl/article/abc")


def test_content_batch_processor_uses_shared_is_heavy_url():
    """scripts.content_batch_processor must not define its own list."""
    from src.functions.url_content_extraction.scripts import content_batch_processor
    from src.functions.url_content_extraction.core.extractors.extractor_factory import (
        is_heavy_url,
    )

    assert content_batch_processor.is_heavy_url is is_heavy_url


# ---------------------------------------------------------------------------
# handle_request (2.11)
# ---------------------------------------------------------------------------


class _StubExtractor:
    def __init__(self, paragraphs: List[str] | None = None, error: str | None = None):
        self._paragraphs = paragraphs or ["A fact.", "Another fact."]
        self._error = error

    def extract(self, url, *, timeout=None, options=None):  # noqa: ARG002
        from src.functions.url_content_extraction.core.contracts.extracted_content import (
            ExtractedContent,
        )

        return ExtractedContent(
            url=url,
            title="Stub Title",
            paragraphs=[] if self._error else self._paragraphs,
            quotes=[],
            error=self._error,
        )


def test_handle_request_rejects_missing_urls():
    from src.functions.url_content_extraction.functions.main import handle_request

    assert handle_request({}).get("status") == "error"
    assert handle_request({"urls": []}).get("status") == "error"


def test_handle_request_preserves_metadata_and_routes_extractor(monkeypatch):
    from src.functions.url_content_extraction.functions import main as mod

    # Skip AMP probe network I/O.
    monkeypatch.setattr(mod, "_prefer_amp_variant", lambda url, logger: (url, False))
    monkeypatch.setattr(
        mod,
        "get_extractor",
        lambda url, force_playwright, prefer_lightweight, logger: _StubExtractor(),
    )

    payload = {
        "urls": [
            {"url": "https://apnews.com/article/abc", "news_url_id": "nid-1"},
        ]
    }
    result = mod.handle_request(payload)
    assert result["status"] == "success"
    assert result["counts"] == {"total": 1, "succeeded": 1}
    article = result["articles"][0]
    # Metadata flowed through.
    assert article.get("news_url_id") == "nid-1"
    assert article["url"] == "https://apnews.com/article/abc"
    assert article["title"] == "Stub Title"
    assert "content" in article
    assert "error" not in article


def test_handle_request_partial_failure_reports_but_continues(monkeypatch):
    from src.functions.url_content_extraction.functions import main as mod

    monkeypatch.setattr(mod, "_prefer_amp_variant", lambda url, logger: (url, False))

    def _fake_get_extractor(url, **_kwargs):
        if "bad" in url:
            return _StubExtractor(error="boom")
        return _StubExtractor()

    monkeypatch.setattr(mod, "get_extractor", _fake_get_extractor)

    payload = {
        "urls": [
            "https://apnews.com/ok",
            "https://apnews.com/bad",
        ]
    }
    result = mod.handle_request(payload)
    # handle_request reports `success` when any URL succeeds; `partial` only
    # when none do. The regression we care about is that per-URL failures
    # don't abort the batch.
    assert result["status"] == "success"
    assert result["counts"]["total"] == 2
    assert result["counts"]["succeeded"] == 1
    errored = [a for a in result["articles"] if "error" in a]
    assert len(errored) == 1


def test_handle_request_raises_become_per_url_errors(monkeypatch):
    """An exception inside extract() should not abort the batch."""
    from src.functions.url_content_extraction.functions import main as mod

    monkeypatch.setattr(mod, "_prefer_amp_variant", lambda url, logger: (url, False))

    class _ExplodingExtractor:
        def extract(self, url, *, timeout=None, options=None):
            raise RuntimeError("network nope")

    monkeypatch.setattr(
        mod, "get_extractor", lambda url, **kw: _ExplodingExtractor()
    )

    result = mod.handle_request({"urls": ["https://apnews.com/x"]})
    assert result["counts"]["total"] == 1
    assert result["counts"]["succeeded"] == 0
    assert result["articles"][0]["error"] == "network nope"


# ---------------------------------------------------------------------------
# Phase 4: Playwright browser reuse (3.1) + LightExtractor shared client (3.2)
# ---------------------------------------------------------------------------


def test_playwright_extractor_exposes_extract_many():
    """`extract_many` must exist on PlaywrightExtractor and accept a URL list."""
    from src.functions.url_content_extraction.core.extractors.playwright_extractor import (
        PlaywrightExtractor,
    )

    extractor = PlaywrightExtractor()
    assert callable(getattr(extractor, "extract_many", None))
    # Empty input is a defined no-op (returns []) — no browser launch.
    assert extractor.extract_many([]) == []


def test_playwright_extract_many_reuses_browser(monkeypatch):
    """`extract_many` must launch the browser exactly once for N URLs."""
    from src.functions.url_content_extraction.core.extractors import playwright_extractor as pe

    launches: list[str] = []
    contexts: list[str] = []
    pages_per_context: list[int] = []

    class FakePage:
        def __init__(self, ctx): self.ctx = ctx; self.url = "about:blank"
        async def close(self): pass

    class FakeContext:
        def __init__(self):
            contexts.append("new")
            pages_per_context.append(0)
        def set_default_navigation_timeout(self, _): pass
        async def new_page(self):
            pages_per_context[-1] += 1
            return FakePage(self)
        async def close(self): pass
        async def add_init_script(self, _): pass

    class FakeBrowser:
        async def new_context(self, **_kwargs):
            return FakeContext()
        async def close(self): pass

    class FakePlaywright:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        @property
        def chromium(self): return self
        async def launch(self, **_kwargs):
            launches.append("launch")
            return FakeBrowser()

    def _fake_playwright(): return FakePlaywright()

    async def _fake_extract_one(self, context, options):
        from src.functions.url_content_extraction.core.contracts.extracted_content import (
            ExtractedContent,
        )
        return ExtractedContent(url=str(options.url), paragraphs=["ok"])

    monkeypatch.setattr(pe, "async_playwright", _fake_playwright)
    monkeypatch.setattr(pe.PlaywrightExtractor, "_extract_one", _fake_extract_one)

    extractor = pe.PlaywrightExtractor()
    results = extractor.extract_many(
        ["https://example.com/a", "https://example.com/b", "https://example.com/c"]
    )
    assert len(results) == 3
    assert all(r.paragraphs == ["ok"] for r in results)
    # Single browser launch + single context shared across all URLs.
    assert len(launches) == 1
    assert len(contexts) == 1


def test_light_extractor_uses_shared_httpx_client():
    """All LightExtractor calls must resolve to the same `httpx.Client`."""
    from src.functions.url_content_extraction.core.extractors import light_extractor

    # Reset and then force two accesses; both should return the same instance.
    light_extractor.close_shared_client()
    c1 = light_extractor._get_shared_client()
    c2 = light_extractor._get_shared_client()
    assert c1 is c2
    light_extractor.close_shared_client()


# ---------------------------------------------------------------------------
# FactsWriter / FactsReader (Phase 3: core/db consolidation)
# ---------------------------------------------------------------------------


class _FakeQuery:
    """Minimal PostgREST-like query builder that records calls and returns
    data from a list-per-call queue. Not exhaustive — just enough for the
    writer/reader paths we actually exercise."""

    def __init__(self, client: "_FakeSupabase", table_name: str, operation: str):
        self.client = client
        self.table_name = table_name
        self.operation = operation
        self.filters: Dict[str, Any] = {}
        self.range_: tuple[int, int] | None = None
        self.payload: Any = None

    def select(self, *_args, **_kwargs): return self
    def insert(self, payload): self.payload = payload; return self
    def update(self, payload): self.payload = payload; return self
    def delete(self): return self

    def eq(self, col, val): self.filters[col] = val; return self
    def in_(self, col, vals): self.filters[col] = ("in", list(vals)); return self
    def is_(self, col, val): self.filters[col] = ("is", val); return self
    def gt(self, col, val): self.filters[col] = (">", val); return self
    def gte(self, col, val): self.filters[col] = (">=", val); return self
    def order(self, *_args, **_kwargs): return self
    def limit(self, *_args, **_kwargs): return self
    def range(self, a, b): self.range_ = (a, b); return self

    def execute(self):
        self.client.calls.append(
            {
                "table": self.table_name,
                "op": self.operation,
                "filters": dict(self.filters),
                "range": self.range_,
                "payload": self.payload,
            }
        )
        # Simulated insert: return one row per input record with generated IDs.
        if self.operation == "insert" and isinstance(self.payload, list):
            data = [
                {"id": f"{self.table_name}-{i}", **row}
                for i, row in enumerate(self.payload)
            ]
            return type("Resp", (), {"data": data})()
        # Simulated select/update/delete: return canned data if queued.
        queued = self.client.data_queue.get(self.table_name, [])
        data = queued.pop(0) if queued else []
        return type("Resp", (), {"data": data})()


class _FakeSupabase:
    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self.data_queue: Dict[str, List[List[Dict[str, Any]]]] = {}

    def queue(self, table: str, rows: List[Dict[str, Any]]):
        self.data_queue.setdefault(table, []).append(rows)

    def table(self, name):
        # Return a query object whose operation is pinned on the next verb call.
        q = _FakeQuery(self, name, operation="select")
        # Shim the verb methods to flip the operation before delegating.
        orig_insert, orig_update, orig_delete = q.insert, q.update, q.delete
        def insert(payload):
            q.operation = "insert"
            return orig_insert(payload)
        def update(payload):
            q.operation = "update"
            return orig_update(payload)
        def delete():
            q.operation = "delete"
            return orig_delete()
        q.insert, q.update, q.delete = insert, update, delete
        return q


def test_facts_writer_insert_facts_returns_ids_and_texts():
    """Writer must return ``(ids_by_article, texts_by_id)`` so embedding
    creation can skip a redundant SELECT against rows we just inserted."""
    from src.functions.url_content_extraction.core.db import FactsWriter

    client = _FakeSupabase()
    writer = FactsWriter(client)
    ids_by_article, texts_by_id = writer.insert_facts(
        {"article-1": ["fact A", "fact B"]}, model="m"
    )
    assert set(ids_by_article["article-1"]) == {"news_facts-0", "news_facts-1"}
    assert set(texts_by_id.values()) == {"fact A", "fact B"}


def test_facts_writer_mark_facts_extracted_buckets_by_count_and_difficulty():
    """Articles with the same (facts_count, difficulty) bucket collapse to a
    single UPDATE. This is the perf fix we can't let regress."""
    from src.functions.url_content_extraction.core.db import FactsWriter

    client = _FakeSupabase()
    writer = FactsWriter(client)
    writer.mark_facts_extracted(
        {
            "a1": ["f"] * 5,   # easy, count=5
            "a2": ["f"] * 5,   # easy, count=5 — same bucket as a1
            "a3": ["f"] * 20,  # medium, count=20
            "a4": ["f"] * 40,  # hard, count=40
        }
    )
    update_calls = [c for c in client.calls if c["op"] == "update" and c["table"] == "news_urls"]
    # 3 buckets → 3 updates (a1+a2 collapse).
    assert len(update_calls) == 3
    ids_updated = []
    for call in update_calls:
        filt = call["filters"].get("id")
        assert filt and filt[0] == "in"
        ids_updated.extend(filt[1])
    assert set(ids_updated) == {"a1", "a2", "a3", "a4"}


def test_facts_writer_mark_single_article_only_backfills_null_content_stamp():
    """Realtime path must leave content_extracted_at alone when it's already
    populated, but backfill when it's null."""
    from src.functions.url_content_extraction.core.db import FactsWriter

    client = _FakeSupabase()
    writer = FactsWriter(client)
    writer.mark_single_article_facts_extracted("nid-1")
    updates = [c for c in client.calls if c["op"] == "update"]
    # First update: unconditional facts_extracted_at.
    assert "facts_extracted_at" in updates[0]["payload"]
    assert updates[0]["filters"].get("id") == "nid-1"
    # Second update: guards on is("content_extracted_at", "null").
    assert "content_extracted_at" in updates[1]["payload"]
    assert updates[1]["filters"].get("content_extracted_at") == ("is", "null")


def test_facts_writer_insert_pooled_embedding_averages():
    """Pooled embedding averages the supplied vectors element-wise."""
    from src.functions.url_content_extraction.core.db import FactsWriter

    client = _FakeSupabase()
    writer = FactsWriter(client)
    ok = writer.insert_pooled_embedding(
        "nid-1",
        vectors=[[1.0, 2.0, 3.0], [3.0, 4.0, 5.0]],
        model="m",
    )
    assert ok is True
    insert_calls = [c for c in client.calls if c["op"] == "insert"]
    payload = insert_calls[-1]["payload"]
    assert payload["embedding_vector"] == [2.0, 3.0, 4.0]
    assert payload["embedding_type"] == "fact_pooled"


def test_facts_writer_insert_pooled_embedding_skips_when_no_vectors():
    """No vectors → no write (returns False)."""
    from src.functions.url_content_extraction.core.db import FactsWriter

    client = _FakeSupabase()
    writer = FactsWriter(client)
    assert writer.insert_pooled_embedding("nid-1", vectors=[], model="m") is False
    assert not [c for c in client.calls if c["op"] == "insert"]


def test_handle_request_invalid_url_entry_does_not_abort(monkeypatch):
    from src.functions.url_content_extraction.functions import main as mod

    monkeypatch.setattr(mod, "_prefer_amp_variant", lambda url, logger: (url, False))
    monkeypatch.setattr(
        mod, "get_extractor", lambda url, **kw: _StubExtractor()
    )

    # Second entry is invalid (int); it should yield an error item but not
    # prevent the first (valid) URL from being processed.
    result = mod.handle_request({"urls": ["https://apnews.com/ok", 42]})
    assert result["counts"]["total"] == 2
    assert result["counts"]["succeeded"] == 1
    assert any("error" in a for a in result["articles"])
