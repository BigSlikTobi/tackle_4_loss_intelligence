"""Configuration helpers for fuzzy search requests and filters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PlayerSearchFilters:
    """Filters that can narrow the player search scope."""

    team: Optional[str] = None
    college: Optional[str] = None
    position: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Optional[dict]) -> "PlayerSearchFilters":
        payload = payload or {}
        return cls(
            team=(payload.get("team") or payload.get("latest_team")),
            college=payload.get("college") or payload.get("collage"),
            position=payload.get("position"),
        )


@dataclass
class GameSearchFilters:
    """Filters for game search queries."""

    weekday: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Optional[dict]) -> "GameSearchFilters":
        payload = payload or {}
        return cls(weekday=payload.get("weekday"))


@dataclass
class FuzzySearchRequest:
    """Normalized fuzzy search request definition."""

    entity_type: str
    query: str
    limit: int = 10
    player_filters: PlayerSearchFilters = field(default_factory=PlayerSearchFilters)
    game_filters: GameSearchFilters = field(default_factory=GameSearchFilters)

    def __post_init__(self) -> None:
        self.entity_type = self._normalize_entity_type(self.entity_type)
        if not self.query:
            raise ValueError("Query text is required for fuzzy search")
        if self.limit <= 0:
            raise ValueError("Limit must be a positive integer")

    @staticmethod
    def _normalize_entity_type(entity_type: str) -> str:
        normalized = (entity_type or "").strip().lower()
        mapping = {
            "player": "players",
            "players": "players",
            "team": "teams",
            "teams": "teams",
            "game": "games",
            "games": "games",
        }
        if normalized not in mapping:
            raise ValueError(
                "Invalid entity_type. Supported values are players, teams, or games"
            )
        return mapping[normalized]

    @classmethod
    def from_dict(cls, payload: dict) -> "FuzzySearchRequest":
        entity_type = payload.get("entity_type") or payload.get("type")
        query = payload.get("query")
        limit = payload.get("limit", 10)

        player_filters = PlayerSearchFilters.from_dict(payload.get("player_filters"))
        game_filters = GameSearchFilters.from_dict(payload.get("game_filters"))

        return cls(
            entity_type=entity_type,
            query=query,
            limit=limit,
            player_filters=player_filters,
            game_filters=game_filters,
        )
