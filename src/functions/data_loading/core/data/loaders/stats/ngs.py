"""Pipeline-backed loader for NFL NextGenStats data."""

from __future__ import annotations

from typing import Any

from .....core.data.fetch import fetch_ngs_data
from .....core.data.transformers.stats import NextGenStatsDataTransformer
from .....core.pipelines import DatasetPipeline, PipelineLoader, SupabaseWriter


def build_ngs_pipeline(stat_type: str, writer=None) -> DatasetPipeline:
    def _fetch(season: int, **_: Any):
        return fetch_ngs_data(season=season, stat_type=stat_type)

    def _transformer_factory() -> NextGenStatsDataTransformer:
        return NextGenStatsDataTransformer(stat_type=stat_type)

    return DatasetPipeline(
        name=f"next_gen_stats:{stat_type}",
        fetcher=_fetch,
        transformer_factory=_transformer_factory,
        writer=writer or SupabaseWriter(
            table_name="next_gen_stats",
            clear_column="player_id",
        ),
    )


class NextGenStatsDataLoader(PipelineLoader):
    """Expose the legacy loader API on top of the new pipeline."""

    def __init__(self, stat_type: str) -> None:
        super().__init__(build_ngs_pipeline(stat_type))
        self.stat_type = stat_type
