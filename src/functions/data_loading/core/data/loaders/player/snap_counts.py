"""Pipeline-backed loader for player snap counts."""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd  # type: ignore

from .....core.data.transformers.player import SnapCountsDataTransformer
from .....core.pipelines import DatasetPipeline, PipelineLoader, SupabaseWriter


def _fetch_snap_counts(season: Optional[int] = None, week: Optional[int] = None, **_: Any):
    from nflreadpy import load_snap_counts  # type: ignore

    df = load_snap_counts(seasons=season)
    df = df.to_pandas() if hasattr(df, "to_pandas") else pd.DataFrame(df)
    if season is not None and "season" in df.columns:
        df = df[df["season"] == season]
    if week is not None and "week" in df.columns:
        df = df[df["week"] == week]
    return df


def build_snap_counts_pipeline(writer=None) -> DatasetPipeline:
    return DatasetPipeline(
        name="snap_counts",
        fetcher=_fetch_snap_counts,
        transformer_factory=SnapCountsDataTransformer,
        writer=writer or SupabaseWriter(
            table_name="snap_counts",
            clear_column="player_id",
        ),
    )


class SnapCountsDataLoader(PipelineLoader):
    """Expose the legacy loader API on top of the new pipeline."""

    def __init__(self, pipeline: Optional[DatasetPipeline] = None) -> None:
        super().__init__(pipeline or build_snap_counts_pipeline())
