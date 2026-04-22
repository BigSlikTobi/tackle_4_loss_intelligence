"""Shared knowledge extraction contracts.

Dataclasses used across knowledge-extraction modules so that the fact-level
pipeline and the article-level on-demand service can share entity resolution
output shapes without importing each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ResolvedEntity:
    """An extracted entity resolved to a canonical database identifier."""

    entity_type: str  # 'player', 'team', or 'game'
    entity_id: str    # player_id, team_abbr, or game_id
    mention_text: str
    matched_name: str
    confidence: float
    is_primary: bool = False
    rank: Optional[int] = None

    position: Optional[str] = None
    team_abbr: Optional[str] = None
    team_name: Optional[str] = None


__all__ = ["ResolvedEntity"]
