from src.functions.knowledge_extraction.core.db.knowledge_writer import (
    KnowledgeWriter,
    _build_entity_dedup_key,
)
from src.functions.knowledge_extraction.core.extraction.topic_extractor import (
    ExtractedTopic,
)
from src.functions.knowledge_extraction.core.resolution.entity_resolver import (
    ResolvedEntity,
)


class _FakeTable:
    def __init__(self, client):
        self._client = client

    def upsert(self, records, on_conflict):
        self._client.last_records = records
        self._client.last_on_conflict = on_conflict
        return self

    def execute(self):
        return type("Resp", (), {"data": self._client.last_records})()


class _FakeSupabaseClient:
    def __init__(self, table_name: str):
        self.table_name = table_name
        self.last_records = None
        self.last_on_conflict = None

    def table(self, name):
        assert name == self.table_name
        return _FakeTable(self)


def test_build_entity_dedup_key_prefers_ids():
    entity_with_id = ResolvedEntity(
        entity_type="player",
        entity_id="Player-123",
        mention_text="Josh Allen",
        matched_name="Josh Allen",
        confidence=0.99,
    )
    entity_without_id = ResolvedEntity(
        entity_type="player",
        entity_id=None,
        mention_text="Josh Allen",
        matched_name="Josh Allen",
        confidence=0.99,
    )

    assert _build_entity_dedup_key(entity_with_id) == "player-123"
    assert _build_entity_dedup_key(entity_without_id) == "josh allen"


def test_write_fact_entities_upserts_unique_records():
    writer = KnowledgeWriter.__new__(KnowledgeWriter)
    writer.client = _FakeSupabaseClient("news_fact_entities")

    entity_primary = ResolvedEntity(
        entity_type="player",
        entity_id="Player-123",
        mention_text="Josh Allen",
        matched_name="Josh Allen",
        confidence=0.9,
        is_primary=True,
    )
    entity_duplicate = ResolvedEntity(
        entity_type="player",
        entity_id="Player-123",
        mention_text="Josh Allen",
        matched_name="Josh Allen",
        confidence=0.8,
        is_primary=False,
    )

    count = writer.write_fact_entities(
        news_fact_id="fact-1",
        entities=[entity_primary, entity_duplicate],
        llm_model="gpt-test",
        dry_run=False,
    )

    assert count == 1
    assert writer.client.last_on_conflict == "news_fact_id,entity_type,entity_dedup_key"
    assert writer.client.last_records[0]["entity_dedup_key"] == "player-123"


def test_write_fact_topics_dedupes_by_canonical_category():
    writer = KnowledgeWriter.__new__(KnowledgeWriter)
    writer.client = _FakeSupabaseClient("news_fact_topics")

    topics = [
        ExtractedTopic(topic="Quarterback Performance & Analysis", confidence=0.7, rank=1),
        ExtractedTopic(topic="Offense Breakdown", confidence=0.6, rank=2),
        ExtractedTopic(topic="Injuries & Player Health", confidence=0.8, rank=1),
        ExtractedTopic(topic="Injury Outlook", confidence=0.9, rank=3),
    ]

    count = writer.write_fact_topics(
        news_fact_id="fact-1",
        topics=topics,
        llm_model="gpt-test",
        dry_run=False,
    )

    assert count == 2
    assert writer.client.last_on_conflict == "news_fact_id,canonical_topic"
    canonical_values = {row["canonical_topic"] for row in writer.client.last_records}
    assert canonical_values == {"offense", "injury"}
    injury_record = next(row for row in writer.client.last_records if row["canonical_topic"] == "injury")
    assert injury_record["topic"] == "injury outlook"
