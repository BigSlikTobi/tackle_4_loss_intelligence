"""Provider for player weekly statistics packages."""

from __future__ import annotations

from typing import Any, Dict, List

from ...core.data.loaders.player.player_weekly_stats import (
    build_player_weekly_stats_pipeline,
)
from ...core.pipelines import NullWriter

from .base import DataProvider


class PlayerWeeklyStatsProvider(DataProvider):
    """Expose weekly player stats filtered by season, week, and player ID."""

    _EXCLUDED_FIELDS = {
        "player_name",
        "player_display_name",
        "position",
        "position_group",
        "headshot_url",
        "season_type",
        "team",
        "opponent_team",
    }

    def __init__(self) -> None:
        pipeline = build_player_weekly_stats_pipeline(writer=NullWriter())
        super().__init__(
            name="player_weekly_stats",
            pipeline=pipeline,
            fetch_keys=("season", "week"),
        )

    # ------------------------------------------------------------------
    def get(self, *, output: str = "dict", **filters: Any) -> Any:  # type: ignore[override]
        missing = [
            key
            for key in ("season", "week")
            if key not in filters or filters[key] is None
        ]
        if missing:
            missing_str = ", ".join(missing)
            raise ValueError(
                f"player_weekly_stats provider requires filters for: {missing_str}"
            )
        player_id = filters.get("player_id")
        if player_id is None or (isinstance(player_id, str) and not player_id.strip()):
            raise ValueError(
                "player_weekly_stats provider requires a 'player_id' filter"
            )
        if isinstance(player_id, (list, tuple, set)) and not player_id:
            raise ValueError(
                "player_weekly_stats provider requires at least one player_id value"
            )
        return super().get(output=output, **filters)

    def _serialise(self, records: List[Dict[str, Any]], output: str) -> Any:  # type: ignore[override]
        cleaned = [
            {key: value for key, value in record.items() if key not in self._EXCLUDED_FIELDS}
            for record in records
        ]
        return super()._serialise(cleaned, output)


__all__ = ["PlayerWeeklyStatsProvider"]
