"""Provider for single-game play-by-play payloads."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from ...core.data.loaders.game.pbp import build_play_by_play_pipeline
from ...core.pipelines import NullWriter

from .base import DataProvider


class PlayByPlayProvider(DataProvider):
    """Expose play-by-play events for a specific game identifier."""

    _GAME_ID_PATTERN = re.compile(r"(?P<season>\d{4})_(?P<week>\d{1,2})_")

    def __init__(self) -> None:
        pipeline = build_play_by_play_pipeline(writer=NullWriter())
        super().__init__(
            name="play_by_play",
            pipeline=pipeline,
            fetch_keys=("season", "week"),
        )

    # ------------------------------------------------------------------
    def get(self, *, output: str = "dict", **filters: Any) -> Any:  # type: ignore[override]
        game_id = filters.pop("game_id", None) or filters.pop("games_id", None)
        if game_id is None:
            raise ValueError("play_by_play provider requires a 'game_id' filter")

        game_id_str = str(game_id).strip()
        if not game_id_str:
            raise ValueError("play_by_play provider received an empty 'game_id'")

        season = filters.get("season")
        week = filters.get("week")
        derived_season, derived_week = self._derive_from_game_id(game_id_str)
        if season is None:
            season = derived_season
        if week is None:
            week = derived_week

        if season is None:
            raise ValueError(
                "play_by_play provider requires a 'season' value either explicitly "
                "or encoded in the game_id (e.g. '2024_05_SF_KC')."
            )

        filters["season"] = season
        if week is not None:
            filters["week"] = week
        filters["game_id"] = game_id_str

        return super().get(output=output, **filters)

    @classmethod
    def _derive_from_game_id(cls, game_id: str) -> Tuple[Optional[int], Optional[int]]:
        match = cls._GAME_ID_PATTERN.search(game_id)
        if not match:
            return None, None
        season_str = match.group("season")
        week_str = match.group("week")
        try:
            season = int(season_str)
        except (TypeError, ValueError):
            season = None
        try:
            week = int(week_str.lstrip("0") or week_str)
        except (TypeError, ValueError):
            week = None
        return season, week


__all__ = ["PlayByPlayProvider"]
