from typing import Dict, List

import pytest

from src.functions.knowledge_extraction.core.extraction.entity_extractor import ExtractedEntity
from src.functions.knowledge_extraction.core.extraction.topic_extractor import ExtractedTopic
from src.functions.knowledge_extraction.core.pipelines.extraction_pipeline import ExtractionPipeline
from src.functions.knowledge_extraction.core.resolution.entity_resolver import ResolvedEntity


class FakeStoryGroupReader:
    def __init__(self, groups: List[Dict] | None = None, summaries: Dict[str, List[Dict]] | None = None):
        self._groups = groups or []
        self._summaries = summaries or {}
        self.unextracted_calls: List[Dict] = []
        self.summary_calls: List[str] = []

    def get_unextracted_groups(self, limit=None, retry_failed=False, max_error_count=3):
        self.unextracted_calls.append(
            {"limit": limit, "retry_failed": retry_failed, "max_error_count": max_error_count}
        )
        return list(self._groups)

    def get_group_summaries(self, group_id: str) -> List[Dict]:
        self.summary_calls.append(group_id)
        return list(self._summaries.get(group_id, []))

    def get_progress_stats(self) -> Dict:
        return {"total_groups": len(self._groups)}


class FakeTopicExtractor:
    def __init__(self, topics: List[ExtractedTopic]):
        self._topics = topics
        self.calls: List[Dict] = []

    def extract(self, text: str, max_topics: int) -> List[ExtractedTopic]:
        self.calls.append({"text": text, "max_topics": max_topics})
        return list(self._topics)


class FakeEntityExtractor:
    def __init__(self, entities: List[ExtractedEntity]):
        self._entities = entities
        self.calls: List[Dict] = []

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
        self.calls: List[Dict] = []

    def write_knowledge(self, story_group_id: str, topics: List[ExtractedTopic], entities: List[ResolvedEntity], dry_run: bool):
        payload = {
            "group_id": story_group_id,
            "topics": list(topics),
            "entities": list(entities),
            "dry_run": dry_run,
        }
        self.calls.append(payload)
        return {"topics": len(topics), "entities": len(entities)}


def test_run_returns_zero_when_no_groups():
    reader = FakeStoryGroupReader(groups=[])
    pipeline = ExtractionPipeline(
        reader=reader,
        writer=FakeKnowledgeWriter(),
        entity_extractor=FakeEntityExtractor([]),
        topic_extractor=FakeTopicExtractor([]),
        entity_resolver=FakeEntityResolver({}),
    )

    result = pipeline.run()

    assert result == {
        "groups_processed": 0,
        "topics_extracted": 0,
        "entities_extracted": 0,
        "groups_with_errors": 0,
        "errors": [],
    }


def test_run_processes_group_and_writes_topics_and_entities():
    group_id = "group-1"
    reader = FakeStoryGroupReader(
        groups=[{"id": group_id}],
        summaries={
            group_id: [
                {"summary_text": "Josh Allen leads the Bills to victory."},
                {"summary_text": "Allen throws four touchdowns."},
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

    assert result["groups_processed"] == 1
    assert result["topics_extracted"] == 1
    assert result["entities_extracted"] == 1
    assert result["groups_with_errors"] == 0
    assert result["errors"] == []

    assert len(writer.calls) == 1
    payload = writer.calls[0]
    assert payload["group_id"] == group_id
    assert len(payload["topics"]) == 1
    assert len(payload["entities"]) == 1
    entity = payload["entities"][0]
    assert entity.is_primary is True
    assert entity.rank == 1
    assert entity.position == "QB"
    assert entity.team_abbr == "BUF"
