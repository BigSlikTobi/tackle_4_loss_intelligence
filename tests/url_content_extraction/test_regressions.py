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


def test_post_processor_reuses_shared_prompt_version():
    from src.functions.url_content_extraction.core.post_processors import (
        fact_extraction as pp,
    )
    from src.functions.url_content_extraction.core.facts.prompts import (
        FACT_PROMPT_VERSION as canonical,
    )

    assert pp.FACT_PROMPT_VERSION == canonical


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
