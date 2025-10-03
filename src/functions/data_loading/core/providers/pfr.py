"""Provider for Pro Football Reference player-season payloads."""

from __future__ import annotations

from typing import Any

from ...core.data.fetch import fetch_pfr_data
from ...core.data.transformers.player import PfrPlayerSeasonDataTransformer
from ...core.pipelines import DatasetPipeline, NullWriter

from .base import DataProvider


class PfrPlayerSeasonProvider(DataProvider):
    """Expose PFR stats for a given player (pfr_id) and season."""

    def __init__(self) -> None:
        pipeline = self._build_pipeline()
        super().__init__(
            name="pfr_player_season",
            pipeline=pipeline,
            fetch_keys=("season",),
        )

    @staticmethod
    def _build_pipeline() -> DatasetPipeline:
        def _fetcher(season: int, week: int | None = None, **_: Any):
            return fetch_pfr_data(season=season, week=week)

        return DatasetPipeline(
            name="pfr_player_season",
            fetcher=_fetcher,
            transformer_factory=PfrPlayerSeasonDataTransformer,
            writer=NullWriter(),
        )

    def get(self, *, output: str = "dict", **filters: Any) -> Any:  # type: ignore[override]
        season = filters.get("season")
        if season is None:
            raise ValueError("pfr provider requires a 'season' filter")

        player_id = filters.pop("pfr_id", None) or filters.pop("player_id", None)
        if player_id is None:
            raise ValueError("pfr provider requires a 'pfr_id' filter")

        normalized_id = self._normalize_identifier(player_id)
        filters["player_id"] = normalized_id
        return super().get(output=output, **filters)

    @staticmethod
    def _normalize_identifier(value: Any) -> str:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("pfr provider received an empty 'pfr_id'")
            return value
        if isinstance(value, (int, float)):
            return str(int(value))
        raise ValueError("pfr provider received an unsupported 'pfr_id' type")


__all__ = ["PfrPlayerSeasonProvider"]
