"""Provider for player-game snap count payloads."""

from __future__ import annotations

import re
from typing import Any, Optional, Tuple

import pandas as pd  # type: ignore

from ...core.data.transformers.player import SnapCountsGameDataTransformer
from ...core.pipelines import DatasetPipeline, NullWriter

from .base import DataProvider


class SnapCountsGameProvider(DataProvider):
    """Expose snap counts for a single player in a specific game."""

    _GAME_ID_PATTERN = re.compile(r"^(?P<season>\d{4})_(?P<week>\d{2})_")

    def __init__(self) -> None:
        pipeline = self._build_pipeline()
        super().__init__(
            name="snap_counts_player_game",
            pipeline=pipeline,
            fetch_keys=("season", "week"),
        )

    @staticmethod
    def _build_pipeline() -> DatasetPipeline:
        def _fetch(season: int, week: Optional[int] = None, **_: Any) -> pd.DataFrame:
            from nflreadpy import load_snap_counts  # type: ignore

            seasons_arg = [season]
            df = load_snap_counts(seasons=seasons_arg)
            df = df.to_pandas() if hasattr(df, "to_pandas") else pd.DataFrame(df)
            if "season" in df.columns:
                df = df[df["season"] == season]
            if week is not None and "week" in df.columns:
                df = df[df["week"] == week]
            return df

        return DatasetPipeline(
            name="snap_counts_player_game",
            fetcher=_fetch,
            transformer_factory=SnapCountsGameDataTransformer,
            writer=NullWriter(),
        )

    def get(self, *, output: str = "dict", **filters: Any) -> Any:  # type: ignore[override]
        game_id = filters.pop("game_id", None) or filters.pop("games_id", None)
        if not game_id:
            raise ValueError("snap_counts provider requires a 'game_id' filter")
        game_id_str = str(game_id).strip()
        if not game_id_str:
            raise ValueError("snap_counts provider received an empty 'game_id'")

        player_id = filters.pop("pfr_id", None) or filters.pop("player_id", None)
        if player_id is None:
            raise ValueError("snap_counts provider requires a 'pfr_id' filter")
        player_id_str = self._normalise_identifier(player_id)

        season = filters.get("season")
        week = filters.get("week")
        derived_season, derived_week = self._derive_from_game_id(game_id_str)
        if season is None:
            season = derived_season
        if week is None:
            week = derived_week

        if season is None:
            raise ValueError(
                "snap_counts provider requires a 'season' value either explicitly or derivable from game_id"
            )

        filters["season"] = season
        if week is not None:
            filters["week"] = week
        filters["player_id"] = player_id_str
        filters["game_id"] = game_id_str

        return super().get(output=output, **filters)

    @staticmethod
    def _normalise_identifier(value: Any) -> str:
        if isinstance(value, str):
            candidate = value.strip()
            if not candidate:
                raise ValueError("snap_counts provider received an empty 'pfr_id'")
            return candidate
        if isinstance(value, (int, float)):
            return str(int(value))
        raise ValueError("snap_counts provider received an unsupported 'pfr_id' type")

    @classmethod
    def _derive_from_game_id(cls, game_id: str) -> Tuple[Optional[int], Optional[int]]:
        match = cls._GAME_ID_PATTERN.match(game_id)
        if not match:
            return None, None
        season_raw = match.group("season")
        week_raw = match.group("week")
        try:
            season = int(season_raw)
        except (TypeError, ValueError):
            season = None
        try:
            week = int(week_raw.lstrip("0") or week_raw)
        except (TypeError, ValueError):
            week = None
        return season, week


__all__ = ["SnapCountsGameProvider"]
