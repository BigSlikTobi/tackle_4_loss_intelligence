from dataclasses import dataclass
from typing import Dict, List

import pytest

from src.functions.news_extraction.core.contracts import NewsItem
from src.functions.news_extraction.core.pipelines.news_pipeline import NewsExtractionPipeline


@dataclass
class FakeSource:
    name: str
    type: str = "rss"


class FakeFeedConfig:
    def __init__(self, sources: List[FakeSource]):
        self._sources = list(sources)
        self.user_agent = "test-agent"
        self.timeout_seconds = 5
        self.max_parallel_fetches = 4

    def get_enabled_sources(self, source_filter: str | None = None) -> List[FakeSource]:
        sources = list(self._sources)
        if source_filter:
            filt = source_filter.lower()
            sources = [source for source in sources if filt in source.name.lower()]
        return sources


class DummyHttpClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeWriter:
    def __init__(self):
        self.writes: List[List[Dict]] = []
        self.cleared = False

    def write(self, records: List[Dict], dry_run: bool = False) -> Dict:
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

    def clear(self, dry_run: bool = False) -> Dict:
        self.cleared = True
        return {"success": True}


def test_extract_returns_zero_when_no_sources():
    config = FakeFeedConfig(sources=[])
    pipeline = NewsExtractionPipeline(config=config, writer=FakeWriter())

    result = pipeline.extract(dry_run=True)

    assert result["success"] is True
    assert result["sources_processed"] == 0
    assert result["items_extracted"] == 0
    assert result["records_written"] == 0


def test_extract_runs_and_writes_unique_records(monkeypatch):
    sources = [FakeSource(name="Source A"), FakeSource(name="Source B")]
    config = FakeFeedConfig(sources=sources)
    writer = FakeWriter()

    items_by_source = {
        "Source A": [
            NewsItem(
                url="https://example.com/a",
                title="Story A1",
                publisher="ESPN",
                source_name="Source A",
            ),
            NewsItem(
                url="https://example.com/b",
                title="Story A2",
                publisher="ESPN",
                source_name="Source A",
            ),
        ],
        "Source B": [
            NewsItem(
                url="https://example.com/b",
                title="Story B1",
                publisher="FOX",
                source_name="Source B",
            ),
            NewsItem(
                url="https://example.com/c",
                title="Story B2",
                publisher="FOX",
                source_name="Source B",
            ),
        ],
    }

    class FakeExtractor:
        def __init__(self, source_type: str):
            self.source_type = source_type

        def extract(self, source, **kwargs):
            return list(items_by_source[source.name])

    monkeypatch.setattr(
        "src.functions.news_extraction.core.pipelines.news_pipeline.get_extractor",
        lambda source_type, http_client: FakeExtractor(source_type),
    )
    monkeypatch.setattr(
        "src.functions.news_extraction.core.pipelines.news_pipeline.HttpClient",
        lambda *args, **kwargs: DummyHttpClient(),
    )

    pipeline = NewsExtractionPipeline(config=config, writer=writer, max_workers=2)

    result = pipeline.extract(dry_run=False)

    assert result["success"] is True
    assert result["sources_processed"] == 2
    assert result["items_extracted"] == 4
    assert result["items_filtered"] == 1  # duplicate filtered out
    assert result["records_written"] == 3

    assert len(writer.writes) == 1
    written_urls = {record["url"] for record in writer.writes[0]}
    assert written_urls == {"https://example.com/a", "https://example.com/b", "https://example.com/c"}
