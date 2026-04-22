"""Thin wrapper over the shared EntityResolver.

Instantiates a request-scoped resolver (so caches don't leak across requests
in a Cloud Function) and splits extracted entities into resolved vs unresolved.
"""

from __future__ import annotations

import logging
from typing import List, Tuple

from src.shared.contracts.knowledge import ResolvedEntity
from src.shared.nlp.entity_resolver import EntityResolver

from ..extraction.article_entity_extractor import ExtractedEntity

logger = logging.getLogger(__name__)


class ArticleEntityResolver:
    def __init__(self, confidence_threshold: float = 0.6, supabase_client=None):
        self._resolver = EntityResolver(
            confidence_threshold=confidence_threshold,
            client=supabase_client,
        )

    def resolve_all(
        self, extracted: List[ExtractedEntity]
    ) -> Tuple[List[ResolvedEntity], List[ExtractedEntity]]:
        resolved: List[ResolvedEntity] = []
        unresolved: List[ExtractedEntity] = []

        for entity in extracted:
            resolved_entity = None
            try:
                if entity.entity_type == "player":
                    resolved_entity = self._resolver.resolve_player(
                        mention_text=entity.mention_text,
                        position=entity.position,
                        team_abbr=entity.team_abbr,
                        team_name=entity.team_name,
                    )
                elif entity.entity_type == "team":
                    resolved_entity = self._resolver.resolve_team(entity.mention_text)
                elif entity.entity_type == "game":
                    resolved_entity = self._resolver.resolve_game(entity.mention_text)
                elif entity.entity_type == "staff":
                    # Staff is not resolved against a canonical store today; keep as unresolved
                    resolved_entity = None
            except Exception:
                logger.exception(
                    "Resolver raised while processing entity '%s' (%s)",
                    entity.mention_text,
                    entity.entity_type,
                )
                resolved_entity = None

            if resolved_entity is None:
                unresolved.append(entity)
                continue

            # Carry through rank + player-specific disambiguation
            resolved_entity.rank = entity.rank
            if entity.entity_type == "player":
                resolved_entity.position = entity.position
                resolved_entity.team_abbr = entity.team_abbr
                resolved_entity.team_name = entity.team_name

            resolved.append(resolved_entity)

        return resolved, unresolved
