"""Pipeline-backed loader for weekly player statistics."""

from __future__ import annotations

from typing import Any, Optional

from .....core.data.fetch import fetch_weekly_stats_data
from .....core.data.transformers.player import PlayerWeeklyStatsDataTransformer
from .....core.pipelines import DatasetPipeline, PipelineLoader, SupabaseWriter


def _fetch_player_weekly_stats(season: int, week: Optional[int] = None, **_: Any):
    return fetch_weekly_stats_data(season=season, week=week)


def build_player_weekly_stats_pipeline(writer=None) -> DatasetPipeline:
    return DatasetPipeline(
        name="player_weekly_stats",
        fetcher=_fetch_player_weekly_stats,
        transformer_factory=PlayerWeeklyStatsDataTransformer,
        writer=writer or SupabaseWriter(
            table_name="player_weekly_stats",
            clear_column="stat_id",
        ),
    )


class PlayerWeeklyStatsDataLoader(PipelineLoader):
    """Expose the legacy loader API on top of the new pipeline."""

    def __init__(self, pipeline: Optional[DatasetPipeline] = None) -> None:
        super().__init__(pipeline or build_player_weekly_stats_pipeline())
