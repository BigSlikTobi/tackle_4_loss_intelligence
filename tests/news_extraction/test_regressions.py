"""Regression tests for recent news_extraction fixes.

- Watermarks must not advance for sources whose items don't survive dedup.
- UrlProcessor must not leak state across calls (Cloud Function warm starts).
- Cache stats must report real hit/miss counters.
- Dates from feeds must be normalised to tz-aware UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List

import pytest

from src.functions.news_extraction.core.contracts import NewsItem
from src.functions.news_extraction.core.pipelines.news_pipeline import (
    NewsExtractionPipeline,
)
from src.functions.news_extraction.core.processors import UrlProcessor
from src.functions.news_extraction.core.utils.dates import ensure_utc, parse_feed_date


@dataclass
class FakeSource:
    name: str
    type: str = "rss"


class FakeFeedConfig:
    def __init__(self, sources: List[FakeSource]):
        self._sources = list(sources)
        self.user_agent = "test-agent"
        self.timeout_seconds = 5
        self.max_workers = 2
        self.max_requests_per_minute_per_source = 60

    def get_enabled_sources(self, source_filter: str | None = None):
        sources = list(self._sources)
        if source_filter:
            filt = source_filter.lower()
            sources = [s for s in sources if filt in s.name.lower()]
        return sources


class DummyHttpClient:
    def __init__(self, *args, **kwargs):
        pass

    def close(self):
        pass


class RecordingWatermarkStore:
    def __init__(self, initial=None):
        self.watermarks: Dict[str, datetime] = dict(initial or {})
        self.update_calls: List[Dict[str, datetime]] = []

    def fetch_watermarks(self):
        return dict(self.watermarks)

    def update_watermarks(self, updates):
        self.update_calls.append(dict(updates))
        self.watermarks.update(updates)


class FakeWriter:
    def __init__(self):
        self.writes: List[List[Dict]] = []

    def write(self, records, dry_run: bool = False):
        self.writes.append(list(records))
        return {
            "success": True,
            "records_written": len(records),
            "new_records": len(records),
            "skipped_records": 0,
            "batches_processed": 1,
            "failed_batches": 0,
            "write_time_seconds": 0.01,
        }

    def clear(self, dry_run: bool = False):
        return {"success": True}


def _patch_pipeline_deps(monkeypatch, items_by_source):
    class FakeExtractor:
        def __init__(self, source_type):
            self.source_type = source_type

        def extract(self, source, **_kwargs):
            return list(items_by_source.get(source.name, []))

    monkeypatch.setattr(
        "src.functions.news_extraction.core.pipelines.news_pipeline.get_extractor",
        lambda source_type, http_client: FakeExtractor(source_type),
    )
    monkeypatch.setattr(
        "src.functions.news_extraction.core.pipelines.news_pipeline.HttpClient",
        lambda *args, **kwargs: DummyHttpClient(),
    )


def test_watermark_not_advanced_when_source_is_fully_deduped(monkeypatch):
    """Source A's items are all duplicates of Source B. A's watermark must stay put."""
    april = datetime(2026, 4, 10, tzinfo=timezone.utc)
    may = datetime(2026, 5, 10, tzinfo=timezone.utc)

    items_by_source = {
        "Source A": [
            NewsItem(
                url="https://example.com/shared",
                title="dup",
                publisher="A",
                source_name="Source A",
                published_date=april,
            ),
        ],
        "Source B": [
            NewsItem(
                url="https://example.com/shared",
                title="first",
                publisher="B",
                source_name="Source B",
                published_date=may,
            ),
            NewsItem(
                url="https://example.com/unique-b",
                title="second",
                publisher="B",
                source_name="Source B",
                published_date=may,
            ),
        ],
    }

    _patch_pipeline_deps(monkeypatch, items_by_source)

    watermarks = RecordingWatermarkStore()
    # Source B listed first so its items are dedup-primary; A's single item is
    # then a duplicate and must not advance A's watermark.
    config = FakeFeedConfig(sources=[FakeSource("Source B"), FakeSource("Source A")])
    pipeline = NewsExtractionPipeline(
        config=config,
        writer=FakeWriter(),
        watermark_store=watermarks,
        max_workers=1,
    )

    result = pipeline.extract(dry_run=False)
    pipeline.close()
    assert result["success"] is True

    assert len(watermarks.update_calls) == 1
    updates = watermarks.update_calls[0]
    # Source B contributed items and must advance. Source A's single item was
    # deduped by Source B's earlier-processed entry, so A must NOT advance.
    assert "Source B" in updates
    assert "Source A" not in updates


def test_watermark_advances_when_source_contributes(monkeypatch):
    published = datetime(2026, 4, 15, tzinfo=timezone.utc)
    items_by_source = {
        "Source A": [
            NewsItem(
                url="https://example.com/a",
                title="only",
                publisher="A",
                source_name="Source A",
                published_date=published,
            ),
        ],
    }
    _patch_pipeline_deps(monkeypatch, items_by_source)

    watermarks = RecordingWatermarkStore()
    config = FakeFeedConfig(sources=[FakeSource("Source A")])
    pipeline = NewsExtractionPipeline(
        config=config, writer=FakeWriter(), watermark_store=watermarks, max_workers=1
    )
    result = pipeline.extract(dry_run=False)
    pipeline.close()

    assert result["success"] is True
    assert watermarks.update_calls == [{"Source A": published}]


def test_url_processor_does_not_leak_state_across_calls():
    """Second call must treat previously-seen URLs as fresh."""
    processor = UrlProcessor()
    items = [
        NewsItem(url="https://example.com/x", title="t", publisher="p", source_name="s"),
    ]
    first = processor.process(items, deduplicate=True)
    second = processor.process(items, deduplicate=True)
    assert len(first) == 1
    assert len(second) == 1, "second call leaked 'seen' state from the first"


def test_parse_feed_date_normalises_to_utc():
    # Naive string interpreted as UTC
    d = parse_feed_date("2026-04-10T12:00:00")
    assert d is not None and d.tzinfo == timezone.utc

    # Timezone-aware string is converted to UTC
    d = parse_feed_date("2026-04-10T12:00:00+02:00")
    assert d is not None and d.tzinfo == timezone.utc
    assert d.hour == 10

    # ensure_utc on a naive datetime
    assert ensure_utc(datetime(2026, 4, 10, 12, 0)).tzinfo == timezone.utc


def test_nfl_only_false_does_not_filter():
    """`nfl_only=False` must mean 'don't enforce NFL filter', not 'exclude NFL'."""
    processor = UrlProcessor()
    items = [
        NewsItem(
            url="https://example.com/a",
            title="nfl",
            publisher="p",
            source_name="s",
            is_nfl_content=True,
        ),
        NewsItem(
            url="https://example.com/b",
            title="other",
            publisher="p",
            source_name="s",
            is_nfl_content=False,
        ),
    ]
    passed = processor.process(items, nfl_only=False)
    assert len(passed) == 2

    # Explicit True filters out non-NFL:
    nfl_only = processor.process(items, nfl_only=True)
    assert len(nfl_only) == 1
    assert nfl_only[0].is_nfl_content is True


def test_rate_limiter_is_thread_safe():
    """Concurrent acquire() calls must never raise or exceed the cap."""
    import threading
    from src.functions.news_extraction.core.utils.client import RateLimiter

    limiter = RateLimiter(max_requests=100, window_seconds=60)
    errors = []

    def worker():
        try:
            for _ in range(10):
                limiter.acquire()
        except Exception as exc:  # pragma: no cover - shouldn't happen
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"thread-safety violation: {errors}"
    # 8 workers * 10 calls = 80 acquires; well under the 100 cap so no blocking.
    assert len(limiter.requests) == 80


def test_simple_cache_reports_real_hit_rate():
    from src.functions.news_extraction.core.utils.client import SimpleCache

    cache = SimpleCache(max_size=4, default_ttl=60)

    class DummyResponse:
        status_code = 200

    # Miss, then put, then hit
    assert cache.get("https://example.com/a") is None
    cache.put("https://example.com/a", DummyResponse())
    assert cache.get("https://example.com/a") is not None

    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert 0 < stats["hit_rate"] <= 1
