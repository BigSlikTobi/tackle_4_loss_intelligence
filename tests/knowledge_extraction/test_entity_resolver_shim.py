"""Regression test: the re-export shim in knowledge_extraction preserves the
original import paths after EntityResolver and ResolvedEntity moved to
src/shared/. If this test fails, callers inside knowledge_extraction are about
to break.
"""

from src.functions.knowledge_extraction.core.resolution.entity_resolver import (
    EntityResolver,
    ResolvedEntity,
)
from src.shared.contracts.knowledge import ResolvedEntity as SharedResolvedEntity
from src.shared.nlp.entity_resolver import EntityResolver as SharedEntityResolver


def test_shim_points_at_shared_entity_resolver():
    assert EntityResolver is SharedEntityResolver


def test_shim_points_at_shared_resolved_entity():
    assert ResolvedEntity is SharedResolvedEntity


def test_resolved_entity_is_constructible():
    entity = ResolvedEntity(
        entity_type="team",
        entity_id="KC",
        mention_text="Chiefs",
        matched_name="Kansas City Chiefs",
        confidence=1.0,
    )
    assert entity.entity_type == "team"
    assert entity.entity_id == "KC"
    assert entity.rank is None
    assert entity.is_primary is False
