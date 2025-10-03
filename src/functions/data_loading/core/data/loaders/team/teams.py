"""Pipeline-backed loader for NFL team metadata."""

from __future__ import annotations

from typing import Optional

from .....core.data.fetch import fetch_team_data
from .....core.data.transformers.team import TeamDataTransformer
from .....core.pipelines import DatasetPipeline, PipelineLoader, SupabaseWriter


def build_teams_pipeline(writer=None) -> DatasetPipeline:
    return DatasetPipeline(
        name="teams",
        fetcher=lambda **params: fetch_team_data(season=params.get("season")),
        transformer_factory=TeamDataTransformer,
        writer=writer or SupabaseWriter(
            table_name="teams",
            clear_column="team_abbr",
            conflict_columns=["team_abbr"],
        ),
    )


class TeamsDataLoader(PipelineLoader):
    """Expose the legacy loader API on top of the new pipeline."""

    def __init__(self, pipeline: Optional[DatasetPipeline] = None) -> None:
        super().__init__(pipeline or build_teams_pipeline())
