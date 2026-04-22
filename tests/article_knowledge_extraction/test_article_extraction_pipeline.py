"""Pipeline test with injected fake extractors/resolver — no network calls."""

from __future__ import annotations

from typing import List, Tuple

from src.functions.article_knowledge_extraction.core.config import (
    ArticleInput,
    ExtractionOptions,
)
from src.functions.article_knowledge_extraction.core.extraction.article_entity_extractor import (
    ExtractedEntity,
)
from src.functions.article_knowledge_extraction.core.extraction.article_topic_extractor import (
    ExtractedTopic,
)
from src.functions.article_knowledge_extraction.core.pipelines.article_extraction_pipeline import (
    ArticleExtractionPipeline,
    PipelineDeps,
)
from src.shared.contracts.knowledge import ResolvedEntity


class _FakeTopicExtractor:
    model = "fake-model"

    def extract(self, text: str, max_topics: int) -> List[ExtractedTopic]:
        return [
            ExtractedTopic(topic="Quarterback Performance & Analysis", confidence=0.95, rank=1),
            ExtractedTopic(topic="Game Analysis & Highlights", confidence=0.7, rank=2),
        ][:max_topics]


class _FakeEntityExtractor:
    def extract(self, text: str, max_entities: int) -> List[ExtractedEntity]:
        return [
            ExtractedEntity(
                entity_type="player",
                mention_text="Josh Allen",
                confidence=0.98,
                rank=1,
                position="QB",
                team_abbr="BUF",
                team_name="Buffalo Bills",
            ),
            ExtractedEntity(
                entity_type="team",
                mention_text="Chiefs",
                confidence=0.9,
                rank=2,
            ),
            ExtractedEntity(
                entity_type="player",
                mention_text="Unknown Backup",
                confidence=0.4,
                rank=3,
                position="QB",
                team_abbr="BUF",
            ),
        ][:max_entities]


class _FakeResolver:
    """Resolves Josh Allen and Chiefs; leaves the third entity unresolved."""

    def resolve_all(
        self, extracted: List[ExtractedEntity]
    ) -> Tuple[List[ResolvedEntity], List[ExtractedEntity]]:
        resolved: List[ResolvedEntity] = []
        unresolved: List[ExtractedEntity] = []
        for e in extracted:
            if e.mention_text == "Josh Allen":
                resolved.append(
                    ResolvedEntity(
                        entity_type="player",
                        entity_id="00-allen",
                        mention_text="Josh Allen",
                        matched_name="Josh Allen",
                        confidence=1.0,
                        rank=e.rank,
                        position=e.position,
                        team_abbr=e.team_abbr,
                        team_name=e.team_name,
                    )
                )
            elif e.mention_text == "Chiefs":
                resolved.append(
                    ResolvedEntity(
                        entity_type="team",
                        entity_id="KC",
                        mention_text="Chiefs",
                        matched_name="Kansas City Chiefs",
                        confidence=1.0,
                        rank=e.rank,
                    )
                )
            else:
                unresolved.append(e)
        return resolved, unresolved


def _pipeline() -> ArticleExtractionPipeline:
    return ArticleExtractionPipeline(
        PipelineDeps(
            topic_extractor=_FakeTopicExtractor(),
            entity_extractor=_FakeEntityExtractor(),
            resolver=_FakeResolver(),
        )
    )


def test_pipeline_produces_topics_entities_and_unresolved():
    pipeline = _pipeline()
    article = ArticleInput(text="Sample article body.", article_id="a-1")
    options = ExtractionOptions()

    result = pipeline.run(article, options)
    payload = result.to_dict()

    assert payload["article_id"] == "a-1"
    assert len(payload["topics"]) == 2
    assert payload["topics"][0]["topic"] == "Quarterback Performance & Analysis"
    assert len(payload["entities"]) == 2
    assert {e["entity_id"] for e in payload["entities"]} == {"00-allen", "KC"}
    assert len(payload["unresolved_entities"]) == 1
    assert payload["unresolved_entities"][0]["mention_text"] == "Unknown Backup"
    assert payload["metrics"]["topics_count"] == 2
    assert payload["metrics"]["entities_count"] == 2
    assert payload["metrics"]["unresolved_count"] == 1
    assert payload["metrics"]["model"] == "fake-model"


def test_pipeline_without_resolver_still_returns_entities():
    pipeline = ArticleExtractionPipeline(
        PipelineDeps(
            topic_extractor=_FakeTopicExtractor(),
            entity_extractor=_FakeEntityExtractor(),
            resolver=None,
        )
    )
    article = ArticleInput(text="Sample body.")
    options = ExtractionOptions(resolve_entities=False)

    result = pipeline.run(article, options).to_dict()

    assert len(result["entities"]) == 3
    assert result["unresolved_entities"] == []
    assert all("entity_id" not in e or e.get("entity_id") is None for e in result["entities"])
