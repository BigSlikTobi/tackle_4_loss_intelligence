"""Provider for injury data from the persisted injuries table."""

from __future__ import annotations

from typing import Any, Dict, List

from ...core.db.database_init import get_supabase_client

from .base import DataProvider


class _EmptyPipeline:
    def prepare(self, **_: Any) -> List[Dict[str, Any]]:
        return []


class InjuriesProvider(DataProvider):
    """Return injuries for a specific season/week with optional team/player filters."""

    def __init__(self) -> None:
        super().__init__(
            name="injuries",
            pipeline=_EmptyPipeline(),  # unused, kept for interface compatibility
            fetch_keys=(),
        )
        self.client = get_supabase_client()
        if self.client is None:
            raise RuntimeError("Supabase client is not available")

    def get(self, *, output: str = "dict", **filters: Any) -> Any:  # type: ignore[override]
        season = filters.get("season")
        week = filters.get("week")
        season_type = str(filters.get("season_type", "REG")).strip().upper()
        team_abbr = str(filters.get("team_abbr", "")).strip().upper()
        player_id = str(filters.get("player_id", "")).strip()

        if season is None:
            raise ValueError("injuries provider requires a 'season' filter")
        if week is None:
            raise ValueError("injuries provider requires a 'week' filter")

        query = (
            self.client.table("injuries")
            .select(
                "season,week,season_type,team_abbr,player_id,player_name,injury,practice_status,game_status,last_update,is_current,version"
            )
            .eq("season", int(season))
            .eq("week", int(week))
            .eq("season_type", season_type)
            .eq("is_current", True)
        )

        if team_abbr:
            query = query.eq("team_abbr", team_abbr)
        if player_id:
            query = query.eq("player_id", player_id)

        response = query.execute()
        error = getattr(response, "error", None)
        if error:
            raise RuntimeError(f"Supabase error while fetching injuries: {error}")

        rows = getattr(response, "data", None) or []
        return self._serialise(rows, output)


__all__ = ["InjuriesProvider"]
