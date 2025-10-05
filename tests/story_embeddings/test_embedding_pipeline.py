import pytest

from src.functions.story_embeddings.core.contracts import SummaryRecord
from src.functions.story_embeddings.core.pipelines.embedding_pipeline import (
    EmbeddingPipeline,
)


class FakeOpenAIClient:
    def __init__(self, should_fail_for=None):
        self.should_fail_for = set(should_fail_for or [])
        self.generated = []

    def generate_embedding(self, text: str):
        if text in self.should_fail_for:
            raise RuntimeError("failed to embed")
        self.generated.append(text)
        return {
            "embedding": [0.1, 0.2, 0.3],
            "model": "test-model",
            "tokens_used": 12,
            "processing_time": 0.05,
        }

    def get_usage_stats(self):
        return {
            "total_requests": len(self.generated),
            "failed_requests": 0,
            "total_tokens": 12 * len(self.generated),
            "estimated_cost_usd": round(len(self.generated) * 12 / 1000 * 0.00002, 4),
        }


class FakeSummaryReader:
    def __init__(self, summaries=None, fail=False, without_count=0):
        self._summaries = list(summaries or [])
        self._fail = fail
        self._without_count = without_count

    def get_summaries_without_embeddings(self, limit=None):
        if self._fail:
            raise RuntimeError("database unavailable")
        if limit is not None:
            return self._summaries[:limit]
        return list(self._summaries)

    def count_summaries_without_embeddings(self):
        return self._without_count


class FakeEmbeddingWriter:
    def __init__(self, existing_ids=None, stats=None):
        self._existing_ids = set(existing_ids or [])
        self._stats = stats or {"total_embeddings": 0}
        self.written_payloads = []

    def check_exists(self, news_url_id: str) -> bool:
        return news_url_id in self._existing_ids

    def write_embeddings(self, embeddings):
        self.written_payloads.append([emb.news_url_id for emb in embeddings])
        return {
            "total": len(embeddings),
            "successful": len(embeddings),
            "failed": 0,
            "errors": [],
        }

    def get_stats(self):
        return self._stats


class TrackingWriter(FakeEmbeddingWriter):
    def __init__(self, existing_ids=None, stats=None, fail_ids=None):
        super().__init__(existing_ids=existing_ids, stats=stats)
        self._fail_ids = set(fail_ids or [])

    def write_embeddings(self, embeddings):
        result = super().write_embeddings(embeddings)
        failed = [emb.news_url_id for emb in embeddings if emb.news_url_id in self._fail_ids]
        if failed:
            result["failed"] = len(failed)
            result["successful"] -= len(failed)
            result["errors"] = [f"Failed to persist {news_url_id}" for news_url_id in failed]
        return result


@pytest.fixture
def sample_summaries():
    return [
        SummaryRecord(news_url_id="keep-1", summary_text="embeddable"),
        SummaryRecord(news_url_id="skip-1", summary_text="to skip"),
        SummaryRecord(news_url_id="fail-1", summary_text="should error"),
    ]


def test_process_summaries_handles_reader_failure():
    pipeline = EmbeddingPipeline(
        openai_client=FakeOpenAIClient(),
        summary_reader=FakeSummaryReader(fail=True),
        embedding_writer=FakeEmbeddingWriter(),
    )

    stats = pipeline.process_summaries_without_embeddings(limit=5)

    assert stats["total"] == 0
    assert stats["errors"] == ["Failed to fetch summaries: database unavailable"]


def test_process_summary_batch_captures_success_skip_and_failures(sample_summaries):
    client = FakeOpenAIClient(should_fail_for={"should error"})
    writer = TrackingWriter(existing_ids={"skip-1"}, fail_ids={"keep-1"})
    pipeline = EmbeddingPipeline(
        openai_client=client,
        summary_reader=FakeSummaryReader(summaries=sample_summaries),
        embedding_writer=writer,
    )

    stats = pipeline.process_summary_batch(sample_summaries)

    assert stats["total"] == 3
    assert stats["successful"] == 0  # success but persistence failed
    assert stats["skipped"] == 1
    assert stats["failed"] == 2  # 1 from LLM failure + 1 from writer failure
    assert len(stats["errors"]) == 2
    assert writer.written_payloads[0] == ["keep-1"]
    assert client.generated == ["embeddable"]
    assert stats["embeddings"][0].news_url_id == "keep-1"


def test_get_progress_info_combines_reader_and_writer_data():
    pipeline = EmbeddingPipeline(
        openai_client=FakeOpenAIClient(),
        summary_reader=FakeSummaryReader(without_count=7),
        embedding_writer=FakeEmbeddingWriter(stats={"total_embeddings": 13}),
    )

    progress = pipeline.get_progress_info()

    assert progress["total_summaries"] == 20
    assert progress["summaries_with_embeddings"] == 13
    assert progress["summaries_without_embeddings"] == 7
    assert progress["completion_percentage"] == pytest.approx(65.0)
