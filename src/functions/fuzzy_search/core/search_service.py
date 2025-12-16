"""Fuzzy search service for players, teams, and games."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

from rapidfuzz import fuzz, process

from src.shared.db.connection import get_supabase_client
from src.functions.fuzzy_search.core.config import (
    FuzzySearchRequest,
    GameSearchFilters,
    PlayerSearchFilters,
)

logger = logging.getLogger(__name__)


@dataclass
class FuzzySearchResult:
    """Structured fuzzy search result."""

    entity_type: str
    score: float
    matched_value: str
    record: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "score": self.score,
            "matched_value": self.matched_value,
            "record": self.record,
        }


class FuzzySearchService:
    """Provides fuzzy search across players, teams, and games."""

    def __init__(
        self,
        client: Optional[Any] = None,
        page_size: int = 500,
        score_cutoff: int = 60,
    ) -> None:
        self.client = client or get_supabase_client()
        self.page_size = page_size
        self.score_cutoff = score_cutoff

    def search(self, request: FuzzySearchRequest) -> List[FuzzySearchResult]:
        """Dispatch search based on entity type."""

        if request.entity_type == "players":
            return self.search_players(
                query=request.query,
                limit=request.limit,
                filters=request.player_filters,
            )
        if request.entity_type == "teams":
            return self.search_teams(query=request.query, limit=request.limit)
        if request.entity_type == "games":
            return self.search_games(
                query=request.query,
                limit=request.limit,
                filters=request.game_filters,
            )

        raise ValueError(
            "Unsupported entity type. Choose from players, teams, or games."
        )

    def search_players(
        self, query: str, limit: int, filters: Optional[PlayerSearchFilters]
    ) -> List[FuzzySearchResult]:
        """Run a fuzzy search over the players table."""

        records = self._fetch_paginated(
            table="players",
            select_columns=(
                "player_id, display_name, first_name, last_name, short_name, "
                "football_name, latest_team, position, college_name"
            ),
            apply_filters=lambda q: self._apply_player_filters(q, filters),
        )

        return self._rank_matches(
            query=query,
            records=records,
            label_builder=self._player_label,
            limit=limit,
            entity_type="player",
        )

    def search_teams(self, query: str, limit: int) -> List[FuzzySearchResult]:
        """Run a fuzzy search over the teams table."""

        records = self._fetch_paginated(
            table="teams",
            select_columns="team_abbr, team_name, team_conference, team_division, team_nick",
            apply_filters=lambda q: q,
        )

        return self._rank_matches(
            query=query,
            records=records,
            label_builder=self._team_label,
            limit=limit,
            entity_type="team",
        )

    def search_games(
        self, query: str, limit: int, filters: Optional[GameSearchFilters]
    ) -> List[FuzzySearchResult]:
        """Run a fuzzy search over the games table."""

        records = self._fetch_paginated(
            table="games",
            select_columns=(
                "game_id, season, week, game_type, home_team, away_team, gameday, weekday"
            ),
            apply_filters=lambda q: self._apply_game_filters(q, filters),
        )

        return self._rank_matches(
            query=query,
            records=records,
            label_builder=self._game_label,
            limit=limit,
            entity_type="game",
        )

    def _fetch_paginated(
        self,
        table: str,
        select_columns: str,
        apply_filters: Callable[[Any], Any],
    ) -> List[Dict[str, Any]]:
        """Fetch data from Supabase with pagination support."""

        offset = 0
        rows: List[Dict[str, Any]] = []

        while True:
            query = self.client.table(table).select(select_columns)
            query = apply_filters(query)
            response = query.range(offset, offset + self.page_size - 1).execute()

            rows.extend(response.data)
            logger.debug(
                "Fetched %d %s rows (offset=%d)", len(response.data), table, offset
            )

            if len(response.data) < self.page_size:
                break

            offset += self.page_size

        logger.info("Fetched %d rows from %s", len(rows), table)
        return rows

    def _rank_matches(
        self,
        query: str,
        records: Iterable[Dict[str, Any]],
        label_builder: Callable[[Dict[str, Any]], Optional[str]],
        limit: int,
        entity_type: str,
    ) -> List[FuzzySearchResult]:
        """Rank records by fuzzy similarity to the query string."""

        candidates = []
        for record in records:
            label = label_builder(record)
            if label:
                candidates.append((label, record))

        matches = process.extract(
            query,
            candidates,
            processor=lambda choice: choice[0],
            scorer=fuzz.WRatio,
            limit=limit,
            score_cutoff=self.score_cutoff,
        )

        results: List[FuzzySearchResult] = []
        for choice, score, _ in matches:
            label, record = choice
            results.append(
                FuzzySearchResult(
                    entity_type=entity_type,
                    score=score,
                    matched_value=label,
                    record=record,
                )
            )

        return results

    @staticmethod
    def _player_label(record: Dict[str, Any]) -> Optional[str]:
        """Build a descriptive label for player records."""

        names = [
            record.get("display_name"),
            record.get("football_name"),
            record.get("short_name"),
        ]

        first = record.get("first_name")
        last = record.get("last_name")
        if first or last:
            names.append(" ".join(filter(None, [first, last])))

        label = next((name for name in names if name), None)
        if label and record.get("latest_team"):
            label = f"{label} ({record['latest_team']})"
        return label

    @staticmethod
    def _team_label(record: Dict[str, Any]) -> Optional[str]:
        """Build a descriptive label for team records."""

        name = record.get("team_name") or record.get("team_nick")
        abbr = record.get("team_abbr")
        if name and abbr:
            return f"{name} ({abbr})"
        return name or abbr

    @staticmethod
    def _game_label(record: Dict[str, Any]) -> Optional[str]:
        """Build a descriptive label for game records."""

        home = record.get("home_team")
        away = record.get("away_team")
        if not home or not away:
            return None

        parts = [f"{away} at {home}"]
        if record.get("week"):
            parts.append(f"Week {record['week']}")
        if record.get("season"):
            parts.append(str(record["season"]))
        if record.get("weekday"):
            parts.append(record["weekday"])

        return " | ".join(parts)

    @staticmethod
    def _apply_player_filters(query: Any, filters: Optional[PlayerSearchFilters]) -> Any:
        """Apply player-specific filters to a Supabase query."""

        filters = filters or PlayerSearchFilters()

        if filters.team:
            query = query.eq("latest_team", filters.team.upper())
        if filters.position:
            query = query.ilike("position", f"%{filters.position}%")
        if filters.college:
            query = query.ilike("college_name", f"%{filters.college}%")

        return query

    @staticmethod
    def _apply_game_filters(query: Any, filters: Optional[GameSearchFilters]) -> Any:
        """Apply game-specific filters to a Supabase query."""

        filters = filters or GameSearchFilters()

        if filters.weekday:
            query = query.ilike("weekday", f"%{filters.weekday}%")

        return query
