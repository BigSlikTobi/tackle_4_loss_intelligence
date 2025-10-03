"""Provider for Next Gen Stats player-week payloads."""

from __future__ import annotations

from typing import Any, List

from ...core.data.loaders.stats.ngs import build_ngs_pipeline
from ...core.pipelines import NullWriter

from .base import DataProvider


class NextGenStatsProvider(DataProvider):
    """Expose Next Gen Stats metrics scoped to a player and week."""

    def __init__(self, *, stat_type: str) -> None:
        stat_type_clean = (stat_type or "").strip()
        if not stat_type_clean:
            raise ValueError("NextGenStatsProvider requires a non-empty stat_type")

        self.stat_type = stat_type_clean
        pipeline = build_ngs_pipeline(stat_type=stat_type_clean, writer=NullWriter())
        super().__init__(
            name=f"next_gen_stats:{stat_type_clean}",
            pipeline=pipeline,
            fetch_keys=("season",),
        )

    # ------------------------------------------------------------------
    def get(self, *, output: str = "dict", **filters: Any) -> Any:  # type: ignore[override]
        season = filters.get("season")
        if season is None:
            raise ValueError("next_gen_stats provider requires a 'season' filter")
        if isinstance(season, str):
            season_stripped = season.strip()
            if not season_stripped:
                raise ValueError("next_gen_stats provider received an empty 'season'")
            try:
                filters["season"] = int(season_stripped)
            except ValueError as exc:
                raise ValueError(
                    "next_gen_stats provider requires an integer season value"
                ) from exc

        week = filters.get("week")
        if week is None:
            raise ValueError("next_gen_stats provider requires a 'week' filter")
        if isinstance(week, str):
            week_stripped = week.strip()
            if not week_stripped:
                raise ValueError("next_gen_stats provider received an empty 'week'")
            try:
                filters["week"] = int(week_stripped)
            except ValueError:
                filters["week"] = week_stripped
        elif isinstance(week, (list, tuple, set)):
            cleaned_weeks: List[Any] = []
            for value in week:
                if value is None:
                    continue
                if isinstance(value, str):
                    value = value.strip()
                    if not value:
                        continue
                    try:
                        value = int(value)
                    except ValueError:
                        pass
                cleaned_weeks.append(value)
            if not cleaned_weeks:
                raise ValueError(
                    "next_gen_stats provider requires at least one non-empty week value"
                )
            filters["week"] = cleaned_weeks

        player_id = filters.get("player_id")
        if player_id is None:
            raise ValueError("next_gen_stats provider requires a 'player_id' filter")
        if isinstance(player_id, str):
            player_id_stripped = player_id.strip()
            if not player_id_stripped:
                raise ValueError("next_gen_stats provider received an empty 'player_id'")
            filters["player_id"] = player_id_stripped
        elif isinstance(player_id, (list, tuple, set)):
            cleaned = [str(value).strip() for value in player_id if str(value).strip()]
            if not cleaned:
                raise ValueError(
                    "next_gen_stats provider requires at least one non-empty player_id value"
                )
            filters["player_id"] = cleaned
        else:
            try:
                filters["player_id"] = str(player_id).strip()
            except Exception as exc:  # pragma: no cover - defensive
                raise ValueError("next_gen_stats provider could not normalise player_id") from exc
            if not filters["player_id"]:
                raise ValueError(
                    "next_gen_stats provider requires a non-empty player_id value"
                )

        filters.setdefault("stat_type", self.stat_type)
        return super().get(output=output, **filters)


__all__ = ["NextGenStatsProvider"]
