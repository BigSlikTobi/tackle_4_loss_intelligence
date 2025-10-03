"""Pipeline-backed loader for NFL game schedules."""

from __future__ import annotations

from typing import Any, Iterable, List, Optional

import pandas as pd

from .....core.data.fetch import fetch_game_schedule_data
from .....core.data.transformers.game import GameDataTransformer
from .....core.pipelines import DatasetPipeline, PipelineLoader, SupabaseWriter, PipelineResult
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


def _chunks(items: Iterable[str], size: int) -> Iterable[List[str]]:
    chunk: List[str] = []
    for item in items:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


class GamesSupabaseWriter(SupabaseWriter):
    """Writer that emulates upsert semantics for games by deleting before insert."""

    def write(self, records: List[dict], *, clear: bool = False) -> PipelineResult:
        processed = len(records)
        if not records:
            message = "No game records to write"
            self.logger.info(message)
            return PipelineResult(True, processed, messages=[message])

        game_ids = [rec.get("game_id") for rec in records if rec.get("game_id")]

        messages: List[str] = []
        try:
            if clear:
                self._clear_table()
                messages.append("Cleared table before write")
            elif game_ids:
                for batch in _chunks(game_ids, 200):
                    self.client.table(self.table_name).delete().in_("game_id", batch).execute()
                if game_ids:
                    messages.append(f"Replaced {len(game_ids)} existing games by game_id")

            response = self._perform_write(records)
            error = getattr(response, "error", None)
            if error:
                self.logger.error("Supabase error: %s", error)
                return PipelineResult(False, processed, error=str(error))
            written = len(getattr(response, "data", []) or []) or processed
            return PipelineResult(True, processed, written=written, messages=messages)
        except Exception as exc:  # pragma: no cover
            self.logger.exception("Failed to write records to %s", self.table_name)
            return PipelineResult(False, processed, error=str(exc))


def build_games_pipeline(writer=None) -> DatasetPipeline:
    return DatasetPipeline(
        name="games",
        fetcher=_fetch_games,
        transformer_factory=GameDataTransformer,
        writer=writer or GamesSupabaseWriter(
            table_name="games",
        ),
    )


class GamesDataLoader(PipelineLoader):
    """Expose the legacy loader API on top of the new pipeline."""

    def __init__(self, pipeline: Optional[DatasetPipeline] = None) -> None:
        super().__init__(pipeline or build_games_pipeline())
