"""Pipeline-backed loader for NFL game schedules."""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from .....core.data.fetch import fetch_game_schedule_data
from .....core.data.transformers.game import GameDataTransformer
from .....core.pipelines import DatasetPipeline, PipelineLoader, SupabaseWriter
from .....core.utils.logging import get_logger


logger = get_logger(__name__)


def _fetch_games(season: Optional[int] = None, week: Optional[int] = None, **_: Any):
    df = fetch_game_schedule_data(season=season, week=week)
    if df.empty:
        logger.warning(
            "Game schedule returned no rows for season=%s, week=%s",
            season,
            week,
        )
        return df

    resolved_season = season
    if resolved_season is None and "season" in df.columns:
        numeric = pd.to_numeric(df["season"], errors="coerce")
        numeric = numeric.dropna()
        if not numeric.empty:
            resolved_season = int(numeric.max())
            logger.debug("Detected latest available season %s for schedules", resolved_season)

    if resolved_season is not None and "season" in df.columns:
        df = df[pd.to_numeric(df["season"], errors="coerce") == resolved_season]

    if week is not None and "week" in df.columns:
        df = df[pd.to_numeric(df["week"], errors="coerce") == week]

    if df.empty:
        logger.warning(
            "No game schedules found after filtering for season=%s, week=%s",
            resolved_season,
            week,
        )

    return df


def build_games_pipeline(writer=None) -> DatasetPipeline:
    return DatasetPipeline(
        name="games",
        fetcher=_fetch_games,
        transformer_factory=GameDataTransformer,
        writer=writer or SupabaseWriter(
            table_name="games",
            conflict_columns=["game_id"],
        ),
    )


class GamesDataLoader(PipelineLoader):
    """Expose the legacy loader API on top of the new pipeline."""

    def __init__(self, pipeline: Optional[DatasetPipeline] = None) -> None:
        super().__init__(pipeline or build_games_pipeline())
