"""Pipeline-backed loader for play-by-play data."""

from __future__ import annotations

from typing import Any, Optional

from .....core.data.fetch import fetch_pbp_data
from .....core.data.transformers.game import PlayByPlayDataTransformer
from .....core.pipelines import DatasetPipeline, PipelineLoader, SupabaseWriter


def _fetch_pbp(season: int, week: Optional[int] = None, **_: Any):
    return fetch_pbp_data(season=season, week=week)


def build_play_by_play_pipeline(writer=None) -> DatasetPipeline:
    return DatasetPipeline(
        name="play_by_play",
        fetcher=_fetch_pbp,
        transformer_factory=PlayByPlayDataTransformer,
        writer=writer or SupabaseWriter(
            table_name="play_by_play",
            clear_column="play_id",
        ),
    )


class PlayByPlayDataLoader(PipelineLoader):
    """Expose the legacy loader API on top of the new pipeline."""

    def __init__(self, pipeline: Optional[DatasetPipeline] = None) -> None:
        super().__init__(pipeline or build_play_by_play_pipeline())
