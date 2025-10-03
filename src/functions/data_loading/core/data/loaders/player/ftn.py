"""Pipeline-backed loader for Football Study Hall (FTN) data."""

from __future__ import annotations

from typing import Any, Optional

from .....core.data.fetch import fetch_ftn_data
from .....core.data.transformers.stats import FTNDataTransformer
from .....core.pipelines import DatasetPipeline, PipelineLoader, SupabaseWriter


def _fetch_ftn(season: int, week: Optional[int] = None, **_: Any):
    return fetch_ftn_data(season=season, week=week)


def build_ftn_pipeline(writer=None) -> DatasetPipeline:
    return DatasetPipeline(
        name="ftn_stats",
        fetcher=_fetch_ftn,
        transformer_factory=FTNDataTransformer,
        writer=writer or SupabaseWriter(
            table_name="ftn_stats",
            conflict_columns=["player_id", "season", "week"],
            clear_column="player_id",
        ),
    )


class FootballStudyHallDataLoader(PipelineLoader):
    """Expose the legacy loader API on top of the new pipeline."""

    def __init__(self, pipeline: Optional[DatasetPipeline] = None) -> None:
        super().__init__(pipeline or build_ftn_pipeline())
