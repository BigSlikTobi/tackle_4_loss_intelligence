from typing import Dict, List, Sequence

import pytest

from src.functions.knowledge_extraction.core.extraction.entity_extractor import ExtractedEntity
from src.functions.knowledge_extraction.core.extraction.topic_extractor import ExtractedTopic
from src.functions.knowledge_extraction.core.pipelines.extraction_pipeline import ExtractionPipeline
from src.functions.knowledge_extraction.core.resolution.entity_resolver import ResolvedEntity


class FakeNewsFactReader:
    def __init__(
        self,
        urls: List[Dict] | None = None,
        facts: Dict[str, List[Dict]] | None = None,
        existing_topics: List[str] | None = None,
        existing_entities: List[str] | None = None,
    ):
        self._urls = urls or []
        self._facts = facts or {}
        self._existing_topics = set(existing_topics or [])
        self._existing_entities = set(existing_entities or [])
        self.pending_calls: List[Dict] = []
        self.fact_calls: List[str] = []

    def get_urls_pending_extraction(self, limit=None, retry_failed=False, max_error_count=3):
        self.pending_calls.append(
            {"limit": limit, "retry_failed": retry_failed, "max_error_count": max_error_count}
        )
        return list(self._urls)

    def get_facts_for_url(self, news_url_id: str) -> List[Dict]:
        self.fact_calls.append(news_url_id)
        if news_url_id == "error-url":
            raise RuntimeError("DB connection failed")
        return list(self._facts.get(news_url_id, []))

    def get_existing_topic_fact_ids(self, fact_ids: Sequence[str]) -> List[str]:
        return [fid for fid in fact_ids if fid in self._existing_topics]

    def get_existing_entity_fact_ids(self, fact_ids: Sequence[str]) -> List[str]:
        return [fid for fid in fact_ids if fid in self._existing_entities]

    def get_progress_stats(self) -> Dict:
        return {"facts": 100, "topics": 50, "entities": 50}


class FakeTopicExtractor:
    def __init__(self, topics: List[ExtractedTopic]):
        self._topics = topics
        self.calls: List[Dict] = []
        self.model = "fake-model"

    def extract(self, text: str, max_topics: int) -> List[ExtractedTopic]:
        self.calls.append({"text": text, "max_topics": max_topics})
        return list(self._topics)


class FakeEntityExtractor:
    def __init__(self, entities: List[ExtractedEntity]):
        self._entities = entities
        self.calls: List[Dict] = []
        self.model = "fake-model"

    def extract(self, text: str, max_entities: int) -> List[ExtractedEntity]:
        self.calls.append({"text": text, "max_entities": max_entities})
        return list(self._entities)


class FakeEntityResolver:
    def __init__(self, player_map: Dict[str, ResolvedEntity]):
        self.player_map = player_map
        self.player_calls: List[Dict] = []

    def resolve_player(self, mention_text: str, **kwargs) -> ResolvedEntity | None:
        self.player_calls.append({"mention_text": mention_text, **kwargs})
        return self.player_map.get(mention_text)

    def resolve_team(self, mention_text: str, **kwargs):  # pragma: no cover - not used in tests
        return None

    def resolve_game(self, mention_text: str, **kwargs):  # pragma: no cover - not used in tests
        return None


class FakeKnowledgeWriter:
    def __init__(self):
        self.topic_calls: List[Dict] = []
        self.entity_calls: List[Dict] = []
        self.metric_calls: List[Dict] = []
        self.error_calls: List[Dict] = []

    def write_fact_topics(self, news_fact_id: str, topics: List[ExtractedTopic], llm_model: str, dry_run: bool):
        payload = {
            "news_fact_id": news_fact_id,
            "topics": list(topics),
            "llm_model": llm_model,
            "dry_run": dry_run,
        }
        self.topic_calls.append(payload)
        return len(topics)

    def write_fact_entities(self, news_fact_id: str, entities: List[ResolvedEntity], llm_model: str, dry_run: bool):
        payload = {
            "news_fact_id": news_fact_id,
            "entities": list(entities),
            "llm_model": llm_model,
            "dry_run": dry_run,
        }
        self.entity_calls.append(payload)
        return len(entities)

    def update_article_metrics(self, news_url_id: str, dry_run: bool = False):
        self.metric_calls.append({"news_url_id": news_url_id, "dry_run": dry_run})
        return {}
    
    def increment_error(self, news_url_id: str, error_message: str):
        self.error_calls.append({"news_url_id": news_url_id, "error": error_message})


def test_run_returns_zero_when_no_urls():
    reader = FakeNewsFactReader(urls=[])
    pipeline = ExtractionPipeline(
        reader=reader,
        writer=FakeKnowledgeWriter(),
        entity_extractor=FakeEntityExtractor([]),
        topic_extractor=FakeTopicExtractor([]),
        entity_resolver=FakeEntityResolver({}),
    )

    result = pipeline.run()

    assert result == {
        "urls_processed": 0,
        "facts_processed": 0,
        "topics_written": 0,
        "entities_written": 0,
        "urls_with_errors": 0,
        "errors": [],
    }


def test_run_processes_url_and_writes_topics_and_entities():
    news_url_id = "url-1"
    fact_id = "fact-1"
    
    reader = FakeNewsFactReader(
        urls=[{"id": news_url_id}],
        facts={
            news_url_id: [
                {"id": fact_id, "fact_text": "Josh Allen leads the Bills to victory."},
            ]
        },
    )

    topics = [ExtractedTopic(topic="qb performance", confidence=0.9, rank=1)]
    entities = [
        ExtractedEntity(
            entity_type="player",
            mention_text="Josh Allen",
            context="Josh Allen was unstoppable",
            is_primary=True,
            rank=1,
            position="QB",
            team_abbr="BUF",
            team_name="Buffalo Bills",
        )
    ]

    resolved_entity = ResolvedEntity(
        entity_type="player",
        entity_id="player-123",
        mention_text="Josh Allen",
        matched_name="Josh Allen",
        confidence=0.95,
    )

    writer = FakeKnowledgeWriter()
    
    pipeline = ExtractionPipeline(
        reader=reader,
        writer=writer,
        entity_extractor=FakeEntityExtractor(entities),
        topic_extractor=FakeTopicExtractor(topics),
        entity_resolver=FakeEntityResolver({"Josh Allen": resolved_entity}),
        max_topics=5,
        max_entities=5,
    )

    result = pipeline.run()

    assert result["urls_processed"] == 1
    assert result["facts_processed"] == 1
    assert result["topics_written"] == 1
    assert result["entities_written"] == 1
    assert result["urls_with_errors"] == 0
    assert result["errors"] == []

    # Check topic writes
    assert len(writer.topic_calls) == 1
    topic_payload = writer.topic_calls[0]
    assert topic_payload["news_fact_id"] == fact_id
    assert len(topic_payload["topics"]) == 1

    # Check entity writes
    assert len(writer.entity_calls) == 1
    entity_payload = writer.entity_calls[0]
    assert entity_payload["news_fact_id"] == fact_id
    assert len(entity_payload["entities"]) == 1
    
    entity = entity_payload["entities"][0]
    assert entity.is_primary is True
    assert entity.rank == 1
    # Check resolved fields are populated
    assert entity.position == "QB" 
    assert entity.team_abbr == "BUF"
    
    # Check metric updates
    assert len(writer.metric_calls) == 1
    assert writer.metric_calls[0]["news_url_id"] == news_url_id


def test_run_handles_url_with_no_facts():
    news_url_id = "url-empty"
    reader = FakeNewsFactReader(
        urls=[{"id": news_url_id}],
        facts={},  # No facts
    )
    pipeline = ExtractionPipeline(
        reader=reader,
        writer=FakeKnowledgeWriter(),
        entity_extractor=FakeEntityExtractor([]),
        topic_extractor=FakeTopicExtractor([]),
        entity_resolver=FakeEntityResolver({}),
    )

    result = pipeline.run()

    assert result["urls_processed"] == 0
    assert result["facts_processed"] == 0
    # No metrics updated since we skipped early
    assert len(reader.fact_calls) == 1


def test_run_skips_processed_facts():
    news_url_id = "url-processed"
    fact_id = "fact-fully-done"
    
    reader = FakeNewsFactReader(
        urls=[{"id": news_url_id}],
        facts={
            news_url_id: [{"id": fact_id, "fact_text": "Already done."}]
        },
        existing_topics=[fact_id],
        existing_entities=[fact_id],
    )
    writer = FakeKnowledgeWriter()
    pipeline = ExtractionPipeline(
        reader=reader,
        writer=writer,
        entity_extractor=FakeEntityExtractor([]),
        topic_extractor=FakeTopicExtractor([]),
        entity_resolver=FakeEntityResolver({}),
    )

    result = pipeline.run()

    # URL is processed (counters incremented at the end) but no facts generated work
    assert result["urls_processed"] == 1
    assert result["facts_processed"] == 0
    assert result["topics_written"] == 0
    assert result["entities_written"] == 0
    
    # Only metrics update should happen
    assert len(writer.metric_calls) == 1
    assert len(writer.topic_calls) == 0
    assert len(writer.entity_calls) == 0


def test_run_handles_partially_processed_facts():
    # Scenario: Topics done, entities missing
    news_url_id = "url-partial"
    fact_id = "fact-needs-entities"
    
    reader = FakeNewsFactReader(
        urls=[{"id": news_url_id}],
        facts={
            news_url_id: [{"id": fact_id, "fact_text": "Needs entities."}]
        },
        existing_topics=[fact_id],  # Topics exist
        existing_entities=[],       # Entities missing
    )
    writer = FakeKnowledgeWriter()
    # Mock extractor returns 1 entity
    entities = [ExtractedEntity(entity_type="player", mention_text="Player", is_primary=True, context="")]
    resolved_entity = ResolvedEntity(
        entity_type="player",
        entity_id="p1",
        mention_text="Player",
        is_primary=True,
        matched_name="Player One",
        confidence=0.9
    )
    
    pipeline = ExtractionPipeline(
        reader=reader,
        writer=writer,
        entity_extractor=FakeEntityExtractor(entities),
        topic_extractor=FakeTopicExtractor([]),
        entity_resolver=FakeEntityResolver({"Player": resolved_entity}),
    )

    result = pipeline.run()

    assert result["facts_processed"] == 1
    assert result["topics_written"] == 0   # existing, so skipped
    assert result["entities_written"] == 1 # missing, so processed
    
    # Check calls
    assert len(writer.topic_calls) == 0
    assert len(writer.entity_calls) == 1
    assert len(writer.metric_calls) == 1


def test_run_handles_exception_for_single_url_and_continues():
    # URL 1 -> Error
    # URL 2 -> Success
    reader = FakeNewsFactReader(
        urls=[
            {"id": "error-url"},
            {"id": "success-url"}
        ],
        facts={
            "success-url": [{"id": "fact-1", "fact_text": "OK"}]
        }
    )
    writer = FakeKnowledgeWriter()
    # Mock extractors
    pipeline = ExtractionPipeline(
        reader=reader,
        writer=writer,
        entity_extractor=FakeEntityExtractor([]),
        topic_extractor=FakeTopicExtractor([]),
        entity_resolver=FakeEntityResolver({}),
        continue_on_error=True
    )

    result = pipeline.run()

    assert result["urls_processed"] == 1 # only success-url counts as processed
    assert result["urls_with_errors"] == 1
    assert result["errors"] != []
    
    # Check error loaded
    assert len(writer.error_calls) == 1
    assert writer.error_calls[0]["news_url_id"] == "error-url"
    
    # Check success loaded
    assert len(writer.metric_calls) == 1
    assert writer.metric_calls[0]["news_url_id"] == "success-url"
