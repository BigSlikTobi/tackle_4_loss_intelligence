"""Provider to resolve player IDs from the players table."""

from __future__ import annotations

from typing import Any, Dict, List

from ...core.db.database_init import get_supabase_client

from .base import DataProvider


class _EmptyPipeline:
    def prepare(self, **_: Any) -> List[Dict[str, Any]]:
        return []


class PlayerLookupProvider(DataProvider):
    """Resolve players by name and optional team."""

    def __init__(self) -> None:
        super().__init__(
            name="player_lookup",
            pipeline=_EmptyPipeline(),  # unused, kept for interface compatibility
            fetch_keys=(),
        )
        self.client = get_supabase_client()
        if self.client is None:
            raise RuntimeError("Supabase client is not available")

    def get(self, *, output: str = "dict", **filters: Any) -> Any:  # type: ignore[override]
        player_name = str(filters.get("player_name", "")).strip()
        team_abbr = str(filters.get("team_abbr", "")).strip().upper()
        limit = int(filters.get("limit", 5))

        if not player_name:
            raise ValueError("player_lookup provider requires a 'player_name' filter")

        query = (
            self.client.table("players")
            .select("player_id,display_name,latest_team,position,status,pfr_id")
            .ilike("display_name", f"%{player_name}%")
            .limit(limit)
        )
        if team_abbr:
            query = query.eq("latest_team", team_abbr)

        response = query.execute()
        error = getattr(response, "error", None)
        if error:
            raise RuntimeError(f"Supabase error while looking up player: {error}")

        rows = getattr(response, "data", None) or []
        return self._serialise(rows, output)


__all__ = ["PlayerLookupProvider"]
