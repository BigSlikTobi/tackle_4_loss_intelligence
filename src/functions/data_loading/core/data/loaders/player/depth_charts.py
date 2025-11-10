"""Pipeline-backed loader for team depth charts with versioning support."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

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


def _fetch_depth_charts(team: Optional[str] = None, season: Optional[int] = None, week: Optional[int] = None, **_: Any):
    from nflreadpy import load_depth_charts  # type: ignore

    target_season = season or datetime.now().year
    df = load_depth_charts(seasons=target_season)
    df = df.to_pandas() if hasattr(df, "to_pandas") else pd.DataFrame(df)

    # Add season column if not present (nflreadpy depth charts don't include it)
    if "season" not in df.columns:
        df["season"] = str(target_season)
        logger.debug(f"Added season={target_season} to all depth chart records")
    elif season is not None:
        # Filter to requested season if column exists
        df = df[df["season"] == season]
    
    # Check what week data exists in source
    has_week_col = "week" in df.columns
    if has_week_col:
        source_weeks = df["week"].dropna().unique()
        logger.debug(f"Source data contains weeks: {sorted(source_weeks)}")
    
    # Apply team filtering and get latest snapshot
    if team:
        df = df[df["team"].str.upper() == team.upper()]
        df = _filter_latest(df)
    else:
        df = (
            df.groupby("team", as_index=False, group_keys=False)
            .apply(_filter_latest)
            .reset_index(drop=True)
        )
    
    # Handle week assignment for versioning
    # Depth chart data is typically season-level (week="0") but we allow
    # versioning by week to track when snapshots were taken
    if "week" not in df.columns or df["week"].isna().all():
        df["week"] = "0"
    
    # Convert week to string for consistency
    df["week"] = df["week"].astype(str)
    
    # If user specified a week, use it to label this snapshot
    # This allows tracking "when did we capture this depth chart" vs "what week does the data represent"
    if week is not None:
        logger.info(f"Labeling depth chart snapshot as week={week} (source data week: {df['week'].iloc[0] if len(df) > 0 else 'N/A'})")
        df["week"] = str(week)
    else:
        logger.debug(f"Using source week values: {df['week'].unique() if len(df) > 0 else []}")
    
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
    """Writer that removes conflicting rows, skips missing player/team refs, and supports versioning."""

    allowed_columns = {
        "player_id",
        "team",
        "pos_grp",
        "pos_name",
        "pos_abb",
        "pos_slot",
        "pos_rank",
        "season",
        "week",
        "version",
        "is_current",
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

        # Note: clear is not supported for depth_charts table with versioning
        # Depth charts are automatically versioned per (season, week)
        if clear:
            self.logger.warning(
                "Clear flag ignored for depth_charts table. "
                "Records are automatically versioned per (season, week)."
            )

        try:
            prepared, skipped = self._prepare_records(records)
            messages: List[str] = []

            if not prepared:
                if skipped:
                    messages.append(
                        f"Skipped {len(skipped)} depth chart records due to missing references or season/week"
                    )
                else:
                    messages.append("No depth chart records eligible for insert")
                return PipelineResult(True, processed_total, messages=messages)

            self._ensure_versioning_columns()

            version_map = self._apply_versioning(prepared)

            response = self._perform_write(prepared)
            error = getattr(response, "error", None)
            if error:
                self.logger.error("Supabase error while writing depth charts: %s", error)
                return PipelineResult(False, processed_total, error=str(error))

            self._mark_previous_versions_inactive(version_map)

            written = len(getattr(response, "data", []) or [])
            if not written:
                written = len(prepared)

            if skipped:
                messages.append(
                    f"Skipped {len(skipped)} depth chart records due to missing references or season/week"
                )
            if messages:
                return PipelineResult(True, processed_total, written=written, messages=messages)
            return PipelineResult(True, processed_total, written=written)
        except Exception as exc:  # pragma: no cover
            self.logger.exception("Failed to write depth chart records")
            return PipelineResult(False, processed_total, error=str(exc))

    def _prepare_records(
        self, records: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        prepared: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []

        player_ids = {rec.get("player_id") for rec in records if rec.get("player_id")}
        player_ids = {pid for pid in player_ids if isinstance(pid, str)}
        team_ids = {rec.get("team") for rec in records if rec.get("team")}
        team_ids = {tid for tid in team_ids if isinstance(tid, str)}

        known_players = self._fetch_known_values("players", "player_id", player_ids)
        known_teams = self._fetch_known_values("teams", "team_abbr", team_ids)

        for rec in records:
            player_id = rec.get("player_id")
            team = rec.get("team")
            season = rec.get("season")
            week = rec.get("week")
            
            # For depth charts, week can be "0" for season-level data
            if not season:
                player_label = rec.get("player_name") or player_id or "<unknown>"
                self.logger.warning(
                    "Skipping depth chart entry for %s - missing season", player_label
                )
                skipped.append(rec)
                continue
            
            # If week is missing, default to "0" for season-level depth chart
            if not week:
                rec["week"] = "0"
                week = "0"
            
            missing_reason: Optional[str] = None
            if not player_id or player_id not in known_players:
                missing_reason = "player"
            elif not team or team not in known_teams:
                missing_reason = "team"

            if missing_reason:
                player_label = rec.get("player_name") or player_id or "<unknown>"
                team_label = team or "<no team>"
                if missing_reason == "player":
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
                        "Skipped depth chart row (team=%s, player=%s, slot=%s, rank=%s, season=%s, week=%s)",
                        team_label,
                        player_label,
                        rec.get("pos_slot"),
                        rec.get("pos_rank"),
                        season,
                        week,
                    )
                skipped.append(rec)
                continue

            prepared.append({k: v for k, v in rec.items() if k in self.allowed_columns})

        return prepared, skipped

    def _apply_versioning(self, records: List[Dict[str, Any]]) -> Dict[Tuple[Any, Any], int]:
        """Assign a monotonically increasing version per (season, week)."""

        if not records:
            return {}

        version_map = self._fetch_next_versions(records)

        for record in records:
            scope = (record["season"], record["week"])
            record["version"] = version_map[scope]
            record["is_current"] = True

        return version_map

    def _ensure_versioning_columns(self) -> None:
        """Validate that the depth_charts table exposes the versioning columns."""

        hint = (
            "The depth_charts table must include an integer `version` column and a "
            "boolean `is_current` column (defaulting to true)."
        )

        try:
            response = (
                self.client.table("depth_charts")
                .select("version,is_current")
                .limit(0)
                .execute()
            )
        except Exception as exc:  # pragma: no cover - defensive schema guard
            message = str(exc)
            if "version" in message or "is_current" in message:
                raise RuntimeError(hint) from exc
            raise

        error = getattr(response, "error", None)
        if not error:
            return

        message = str(error)
        if "version" in message or "is_current" in message:
            raise RuntimeError(hint)

        self.logger.warning(
            "Unexpected error while validating depth chart versioning columns: %s",
            message,
        )

    def _fetch_next_versions(self, records: List[Dict[str, Any]]) -> Dict[Tuple[Any, Any], int]:
        scopes = {
            (record["season"], record["week"])
            for record in records
            if record.get("season") and record.get("week")
        }
        version_map: Dict[Tuple[Any, Any], int] = {}

        for season, week in scopes:
            try:
                response = (
                    self.client.table("depth_charts")
                    .select("version")
                    .eq("season", season)
                    .eq("week", week)
                    .order("version", desc=True)
                    .limit(1)
                    .execute()
                )
                data = getattr(response, "data", None) or []
                current_version = 0
                if data:
                    raw_value = data[0].get("version")
                    try:
                        current_version = int(raw_value or 0)
                    except (TypeError, ValueError):
                        self.logger.warning(
                            "Unexpected version value '%s' for %s/%s; defaulting to 0",
                            raw_value,
                            season,
                            week,
                        )
                        current_version = 0
                version_map[(season, week)] = current_version + 1
            except Exception as exc:  # pragma: no cover - guard Supabase errors
                self.logger.exception(
                    "Unable to resolve next version for depth charts %s/%s", season, week
                )
                raise RuntimeError("Failed to calculate depth chart version") from exc

        return version_map

    def _mark_previous_versions_inactive(
        self, version_map: Dict[Tuple[Any, Any], int]
    ) -> None:
        for (season, week), version in version_map.items():
            try:
                response = (
                    self.client.table("depth_charts")
                    .update({"is_current": False})
                    .eq("season", season)
                    .eq("week", week)
                    .lt("version", version)
                    .execute()
                )
                error = getattr(response, "error", None)
                if error:
                    self.logger.warning(
                        "Failed to mark stale depth charts inactive for %s/%s: %s",
                        season,
                        week,
                        error,
                    )
            except Exception:  # pragma: no cover - defensive logging
                self.logger.exception(
                    "Error while marking stale depth charts inactive for %s/%s",
                    season,
                    week,
                )


def build_depth_charts_pipeline(writer=None) -> DatasetPipeline:
    return DatasetPipeline(
        name="depth_charts",
        fetcher=_fetch_depth_charts,
        transformer_factory=DepthChartsDataTransformer,
        writer=writer or DepthChartsSupabaseWriter(
            table_name="depth_charts",
            conflict_columns=None,  # No conflict resolution with versioning - always insert
            clear_column=None,
            clear_guard="",
        ),
    )


class DepthChartsDataLoader(PipelineLoader):
    """Expose the legacy loader API on top of the new pipeline."""

    def __init__(self, pipeline: Optional[DatasetPipeline] = None) -> None:
        super().__init__(pipeline or build_depth_charts_pipeline())
