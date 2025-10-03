"""Pipeline-backed loader for Pro Football Reference weekly stats."""

from __future__ import annotations

from typing import Any, Optional

from .....core.data.fetch import fetch_pfr_data
from .....core.data.transformers.player import PlayerWeeklyStatsDataTransformer
from .....core.pipelines import DatasetPipeline, PipelineLoader, SupabaseWriter


def _fetch_pfr(season: int, week: Optional[int] = None, **_: Any):
    return fetch_pfr_data(season=season, week=week)


def build_pfr_pipeline(writer=None) -> DatasetPipeline:
    return DatasetPipeline(
        name="pfr_weekly_stats",
        fetcher=_fetch_pfr,
        transformer_factory=PlayerWeeklyStatsDataTransformer,
        writer=writer or SupabaseWriter(
            table_name="pfr_weekly_stats",
            conflict_columns=["player_id", "season", "week"],
            clear_column="player_id",
        ),
    )


class ProFootballReferenceDataLoader(PipelineLoader):
    """Expose the legacy loader API on top of the new pipeline."""

    def __init__(self, pipeline: Optional[DatasetPipeline] = None) -> None:
        super().__init__(pipeline or build_pfr_pipeline())
