"""Pipeline-backed loader for player metadata."""

from __future__ import annotations

from typing import Optional

from .....core.data.fetch import fetch_player_data
from .....core.data.transformers.player import PlayerDataTransformer
from .....core.pipelines import DatasetPipeline, PipelineLoader, SupabaseWriter


def _player_fetcher(**params):
    return fetch_player_data(
        season=params.get("season"),
        active_only=params.get("active_only", False),
        min_last_season=params.get("min_last_season"),
    )


def build_players_pipeline(writer=None) -> DatasetPipeline:
    return DatasetPipeline(
        name="players",
        fetcher=_player_fetcher,
        transformer_factory=PlayerDataTransformer,
        writer=writer or SupabaseWriter(
            table_name="players",
            conflict_columns=["player_id"],
            clear_column="player_id",
        ),
    )


class PlayersDataLoader(PipelineLoader):
    """Expose the legacy loader API on top of the new pipeline."""

    def __init__(self, pipeline: Optional[DatasetPipeline] = None) -> None:
        super().__init__(pipeline or build_players_pipeline())
