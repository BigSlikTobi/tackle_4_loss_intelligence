"""Pipeline-backed loader for team rosters with versioning support."""

from __future__ import annotations

import re
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import pandas as pd
from postgrest.exceptions import APIError

from .....core.data.fetch import fetch_weekly_roster_data
from .....core.data.transformers.player import RosterDataTransformer
from .....core.pipelines import DatasetPipeline, PipelineLoader, SupabaseWriter, PipelineResult
from .....core.utils.logging import get_logger


logger = get_logger(__name__)


def _select_latest_values(df: pd.DataFrame, column: str) -> Tuple[pd.DataFrame, Optional[int]]:
    if column not in df.columns:
        return df, None
    numeric = pd.to_numeric(df[column], errors="coerce")
    valid = numeric.dropna()
    if valid.empty:
        return df, None
    latest_value = int(valid.max())
    filtered = df[numeric == latest_value]
    return filtered, latest_value


def _fetch_rosters(season: Optional[int] = None, week: Optional[int] = None, **_: Any):
    df = fetch_weekly_roster_data(season=season)
    resolved_season = season
    resolved_week = week

    if df.empty:
        logger.warning("Roster dataset is empty; nothing to load")
        return df

    if resolved_season is None:
        df, latest_season = _select_latest_values(df, "season")
        resolved_season = latest_season
        if latest_season is not None:
            logger.debug("Using latest roster season %s", latest_season)

    if resolved_season is not None and "season" in df.columns:
        df = df[pd.to_numeric(df["season"], errors="coerce") == resolved_season]

    if resolved_week is None:
        df, latest_week = _select_latest_values(df, "week")
        resolved_week = latest_week
        if latest_week is not None:
            logger.debug("Using latest roster week %s for season %s", latest_week, resolved_season)

    if resolved_week is not None and "week" in df.columns:
        df = df[pd.to_numeric(df["week"], errors="coerce") == resolved_week]

    if resolved_season is None:
        logger.debug("No season value resolved from roster dataset")
    if resolved_week is None:
        logger.debug("No week value resolved from roster dataset")

    if resolved_season is not None:
        df["season"] = int(resolved_season)
    if resolved_week is not None:
        df["week"] = int(resolved_week)

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


class RosterSupabaseWriter(SupabaseWriter):
    """Writer that skips roster rows referencing unknown players and supports versioning."""

    allowed_columns = {
        "team",
        "player",
        "dept_chart_position",
        "season",
        "week",
        "version",
        "is_current",
    }

    def _fetch_known_player_ids(self, player_ids: Set[str]) -> Set[str]:
        if not player_ids:
            return set()
        known: Set[str] = set()
        for batch in _chunks(player_ids, 150):
            response = (
                self.client.table("players")
                .select("player_id")
                .in_("player_id", batch)
                .execute()
            )
            data = getattr(response, "data", None) or []
            for row in data:
                pid = row.get("player_id")
                if isinstance(pid, str):
                    known.add(pid)
        return known

    def write(self, records: List[Dict[str, Any]], *, clear: bool = False) -> PipelineResult:
        processed_total = len(records)
        
        # Note: clear is not supported for rosters table with versioning
        # Rosters are automatically versioned per (season, week)
        if clear:
            self.logger.warning(
                "Clear flag ignored for rosters table. "
                "Records are automatically versioned per (season, week)."
            )
        
        try:
            prepared, skipped = self._prepare_records(records)
            messages: List[str] = []

            if not prepared:
                if skipped:
                    messages.append(
                        f"Skipped {len(skipped)} roster records due to missing player IDs or season/week"
                    )
                return PipelineResult(True, processed_total, messages=messages)

            self._ensure_versioning_columns()

            version_map = self._apply_versioning(prepared)

            response = self._perform_write(prepared)
            error = getattr(response, "error", None)
            if error:
                self.logger.error("Supabase error while writing rosters: %s", error)
                return PipelineResult(False, processed_total, error=str(error))

            self._mark_previous_versions_inactive(version_map)

            written = len(getattr(response, "data", []) or [])
            if not written:
                written = len(prepared)

            if skipped:
                messages.append(
                    f"Skipped {len(skipped)} roster records due to missing player IDs or season/week"
                )
            if messages:
                return PipelineResult(True, processed_total, written=written, messages=messages)
            return PipelineResult(True, processed_total, written=written)
        except Exception as exc:  # pragma: no cover - defensive safety net
            self.logger.exception("Failed to persist roster data")
            return PipelineResult(False, processed_total, error=str(exc))

    def _prepare_records(
        self, records: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        prepared: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        
        player_ids = {rec.get("player") for rec in records if rec.get("player")}
        player_ids = {pid for pid in player_ids if isinstance(pid, str)}
        known_players = self._fetch_known_player_ids(player_ids)

        for record in records:
            season = record.get("season")
            week = record.get("week")
            player_id = record.get("player")
            
            if not season or not week:
                self.logger.warning(
                    "Missing season/week for record: %s", record
                )
                skipped.append(record)
                continue
            
            if not player_id or player_id not in known_players:
                player_label = record.get("player_name") or player_id or "<unknown>"
                team_label = record.get("team") or "<no team>"
                self.logger.warning(
                    "Unable to resolve player '%s' for team %s", player_label, team_label
                )
                skipped.append(record)
                continue

            prepared.append(
                {
                    "season": season,
                    "week": week,
                    "team": record.get("team"),
                    "player": player_id,
                    "dept_chart_position": record.get("dept_chart_position"),
                }
            )

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
        """Validate that the rosters table exposes the versioning columns."""

        hint = (
            "The rosters table must include an integer `version` column and a "
            "boolean `is_current` column (defaulting to true)."
        )

        try:
            response = (
                self.client.table("rosters")
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
            "Unexpected error while validating roster versioning columns: %s",
            message,
        )

    def _fetch_next_versions(self, records: List[Dict[str, Any]]) -> Dict[Tuple[Any, Any], int]:
        scopes = {
            (record["season"], record["week"])
            for record in records
        }
        version_map: Dict[Tuple[Any, Any], int] = {}

        for season, week in scopes:
            try:
                response = (
                    self.client.table("rosters")
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
                    "Unable to resolve next version for rosters %s/%s", season, week
                )
                raise RuntimeError("Failed to calculate roster version") from exc

        return version_map

    def _mark_previous_versions_inactive(
        self, version_map: Dict[Tuple[Any, Any], int]
    ) -> None:
        for (season, week), version in version_map.items():
            try:
                response = (
                    self.client.table("rosters")
                    .update({"is_current": False})
                    .eq("season", season)
                    .eq("week", week)
                    .lt("version", version)
                    .execute()
                )
                error = getattr(response, "error", None)
                if error:
                    self.logger.warning(
                        "Failed to mark stale rosters inactive for %s/%s: %s",
                        season,
                        week,
                        error,
                    )
            except Exception:  # pragma: no cover - defensive logging
                self.logger.exception(
                    "Error while marking stale rosters inactive for %s/%s",
                    season,
                    week,
                )


def build_rosters_pipeline(writer=None) -> DatasetPipeline:
    return DatasetPipeline(
        name="rosters",
        fetcher=_fetch_rosters,
        transformer_factory=RosterDataTransformer,
        writer=writer or RosterSupabaseWriter(
            table_name="rosters",
            conflict_columns=None,  # No conflict resolution with versioning - always insert
            clear_column=None,
            clear_guard="",
        ),
    )


class RostersDataLoader(PipelineLoader):
    """Expose the legacy loader API on top of the new pipeline."""

    def __init__(self, pipeline: Optional[DatasetPipeline] = None) -> None:
        super().__init__(pipeline or build_rosters_pipeline())
