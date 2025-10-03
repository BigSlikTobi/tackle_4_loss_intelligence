"""Pipeline-backed loader for team depth charts."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any, Dict, Iterable, List, Optional, Set

import pandas as pd  # type: ignore

from .....core.data.transformers.player import DepthChartsDataTransformer
from .....core.pipelines import (
    DatasetPipeline,
    PipelineLoader,
    SupabaseWriter,
    PipelineResult,
)
from .....core.utils.logging import get_logger


logger = get_logger(__name__)


def _filter_latest(df: pd.DataFrame) -> pd.DataFrame:
    """Return only the most recent depth chart snapshot for the frame."""
    if df.empty:
        return df

    if "depth_chart_updated" in df.columns:
        updated = pd.to_datetime(df["depth_chart_updated"], errors="coerce")
        if updated.notna().any():
            df = df.loc[updated == updated.max()]

    if "season" in df.columns and not df["season"].isna().all():
        max_season = df["season"].max()
        df = df[df["season"] == max_season]

    if "week" in df.columns and df["week"].notna().any():
        max_week = df.loc[df["week"].notna(), "week"].max()
        df = df[df["week"] == max_week]

    return df


def _fetch_depth_charts(team: Optional[str] = None, season: Optional[int] = None, **_: Any):
    from nflreadpy import load_depth_charts  # type: ignore

    target_season = season or datetime.now().year
    df = load_depth_charts(seasons=target_season)
    df = df.to_pandas() if hasattr(df, "to_pandas") else pd.DataFrame(df)

    if team:
        df = df[df["team"].str.upper() == team.upper()]
        df = _filter_latest(df)
    else:
        df = (
            df.groupby("team", as_index=False, group_keys=False)
            .apply(_filter_latest)
            .reset_index(drop=True)
        )

    if season is not None and "season" in df.columns:
        df = df[df["season"] == season]
    if "season" in df.columns and df["season"].nunique(dropna=True) > 1:
        logger.debug(
            "Depth chart dataset contained multiple seasons; using latest per team"
        )
    if "week" in df.columns and df["week"].nunique(dropna=True) > 1:
        logger.debug(
            "Depth chart dataset contained multiple weeks; using latest per team"
        )
    return df


def _chunks(iterable: Iterable[str], size: int) -> Iterable[List[str]]:
    chunk: List[str] = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


class DepthChartsSupabaseWriter(SupabaseWriter):
    """Writer that removes conflicting rows and skips missing player/team refs."""

    allowed_columns = {
        "player_id",
        "team",
        "pos_grp",
        "pos_name",
        "pos_abb",
        "pos_slot",
        "pos_rank",
    }

    def _fetch_known_values(self, table: str, column: str, values: Set[str]) -> Set[str]:
        if not values:
            return set()
        known: Set[str] = set()
        for batch in _chunks(values, 150):
            response = (
                self.client.table(table)
                .select(column)
                .in_(column, batch)
                .execute()
            )
            data = getattr(response, "data", None) or []
            for row in data:
                value = row.get(column)
                if isinstance(value, str):
                    known.add(value)
        return known

    def write(self, records: List[Dict[str, Any]], *, clear: bool = False) -> PipelineResult:
        processed_total = len(records)

        player_ids = {rec.get("player_id") for rec in records if rec.get("player_id")}
        player_ids = {pid for pid in player_ids if isinstance(pid, str)}
        team_ids = {rec.get("team") for rec in records if rec.get("team")}
        team_ids = {tid for tid in team_ids if isinstance(tid, str)}

        known_players = self._fetch_known_values("players", "player_id", player_ids)
        known_teams = self._fetch_known_values("teams", "team_abbr", team_ids)

        valid_records: List[Dict[str, Any]] = []
        skipped_records: List[Dict[str, Any]] = []

        for rec in records:
            player_id = rec.get("player_id")
            team = rec.get("team")
            missing_reason: Optional[str] = None
            if not player_id or player_id not in known_players:
                missing_reason = "player"
            elif not team or team not in known_teams:
                missing_reason = "team"

            if missing_reason:
                rec["_missing_reason"] = missing_reason
                skipped_records.append(rec)
                continue

            valid_records.append({k: v for k, v in rec.items() if k in self.allowed_columns})

        for miss in skipped_records:
            reason = miss.get("_missing_reason")
            player_label = miss.get("player_name") or miss.get("player_id") or "<unknown>"
            team_label = miss.get("team") or "<no team>"
            if reason == "player":
                self.logger.warning(
                    "Skipping depth chart entry for %s on %s due to missing player record",
                    player_label,
                    team_label,
                )
            else:
                self.logger.warning(
                    "Skipping depth chart entry for %s on %s due to missing team record",
                    player_label,
                    team_label,
                )
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(
                    "Skipped depth chart row (team=%s, player=%s, slot=%s, rank=%s)",
                    team_label,
                    player_label,
                    miss.get("pos_slot"),
                    miss.get("pos_rank"),
                )

        messages: List[str] = []
        if clear:
            self._clear_table()
            messages.append("Cleared table before write")

        if not valid_records:
            if skipped_records:
                messages.append(
                    f"Skipped {len(skipped_records)} depth chart rows with missing references"
                )
            else:
                messages.append("No depth chart records eligible for insert")
            return PipelineResult(True, processed_total, messages=messages)

        try:
            response = self._perform_write(valid_records)
            error = getattr(response, "error", None)
            if error:
                self.logger.error("Supabase error: %s", error)
                return PipelineResult(False, processed_total, error=str(error))
            written = len(getattr(response, "data", []) or []) or len(valid_records)
            if skipped_records:
                messages.append(
                    f"Skipped {len(skipped_records)} depth chart rows with missing references"
                )
            return PipelineResult(True, processed_total, written=written, messages=messages)
        except Exception as exc:  # pragma: no cover
            self.logger.exception("Failed to write depth chart records")
            return PipelineResult(False, processed_total, error=str(exc))


def build_depth_charts_pipeline(writer=None) -> DatasetPipeline:
    return DatasetPipeline(
        name="depth_charts",
        fetcher=_fetch_depth_charts,
        transformer_factory=DepthChartsDataTransformer,
        writer=writer or DepthChartsSupabaseWriter(
            table_name="depth_charts",
            clear_column="player_id",
            clear_guard="",
        ),
    )


class DepthChartsDataLoader(PipelineLoader):
    """Expose the legacy loader API on top of the new pipeline."""

    def __init__(self, pipeline: Optional[DatasetPipeline] = None) -> None:
        super().__init__(pipeline or build_depth_charts_pipeline())
