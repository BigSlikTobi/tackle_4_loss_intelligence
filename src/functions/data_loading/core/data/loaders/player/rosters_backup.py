"""Pipeline-backed loader for team rosters."""

from __future__ import annotations

import re
import logging
import re
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
    """Writer that skips roster rows referencing unknown players."""

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
        
        name_lookup: Dict[str, str] = {}
        player_ids = {rec.get("player") for rec in records if rec.get("player")}
        player_ids = {pid for pid in player_ids if isinstance(pid, str)}
        known_players = self._fetch_known_player_ids(player_ids)

        filtered: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        for rec in records:
            player_id = rec.get("player")
            if isinstance(player_id, str):
                name_lookup.setdefault(player_id, rec.get("player_name") or player_id)
            if not player_id or player_id not in known_players:
                skipped.append(rec)
                continue
            
            # Validate season and week are present for versioning
            season = rec.get("season")
            week = rec.get("week")
            if not season or not week:
                self.logger.warning(
                    "Skipping roster entry for %s - missing season or week",
                    rec.get("player_name") or player_id
                )
                skipped.append(rec)
                continue
            
            filtered.append({k: v for k, v in rec.items() if k in self.allowed_columns})

        for miss in skipped:
            player_label = miss.get("player_name") or miss.get("player") or "<unknown>"
            team_label = miss.get("team") or "<no team>"
            self.logger.warning(
                "Skipping roster entry for %s on %s due to missing player record",
                player_label,
                team_label,
            )

        if self.logger.isEnabledFor(logging.DEBUG):
            for miss in skipped:
                player_label = miss.get("player_name") or miss.get("player") or "<unknown>"
                team_label = miss.get("team") or "<no team>"
                position = miss.get("dept_chart_position") or "<no position>"
                season = miss.get("season")
                week = miss.get("week")
                self.logger.debug(
                    "Skipped roster row (team=%s, player=%s, position=%s, season=%s, week=%s)",
                    team_label,
                    player_label,
                    position,
                    season,
                    week,
                )

        messages: List[str] = []
        db_skipped: List[Dict[str, Any]] = []
        try:
            prepared, skipped_additional = self._prepare_records(filtered)
            skipped.extend(skipped_additional)

            if not prepared:
                if skipped:
                    skipped_count = len(skipped)
                    messages.append(
                        f"Skipped {skipped_count} rows missing player references or season/week"
                    )
                else:
                    messages.append("No roster records eligible for insert")
                return PipelineResult(True, processed_total, messages=messages)

            self._ensure_versioning_columns()

            version_map = self._apply_versioning(prepared)

            remaining = list(prepared)
                if skipped:
                    skipped_count = len(skipped)
                    messages.append(
                        f"Skipped {skipped_count} rows missing player references"
                    )
                else:
                    messages.append("No roster records eligible for insert")
                return PipelineResult(True, processed_total, messages=messages)

            remaining = list(filtered)
            response = None
            while remaining:
                try:
                    response = self._perform_write(remaining)
                    error = getattr(response, "error", None)
                    if error:
                        self.logger.error("Supabase error: %s", error)
                        return PipelineResult(False, processed_total, error=str(error))
                    break
                except APIError as api_error:
                    if getattr(api_error, "code", "") != "23503":
                        raise
                    detail_source = getattr(api_error, "details", None) or getattr(api_error, "message", "")
                    match = re.search(r"Key \(player\)=\(([^)]+)\)", detail_source or "")
                    if not match:
                        raise
                    missing_id = match.group(1)
                    index = next((i for i, row in enumerate(remaining) if row.get("player") == missing_id), None)
                    if index is None:
                        raise
                    miss_record = remaining.pop(index)
                    db_skipped.append(miss_record)
                    player_label = name_lookup.get(missing_id, missing_id)
                    team_label = miss_record.get("team") or "<no team>"
                    self.logger.warning(
                        "Skipping roster entry for %s on %s due to missing player record",
                        player_label,
                        team_label,
                    )
                    if not remaining:
                        continue
                    if self.logger.isEnabledFor(logging.DEBUG):
                        position = miss_record.get("dept_chart_position") or "<no position>"
                        season = miss_record.get("season")
                        week = miss_record.get("week")
                        self.logger.debug(
                            "Skipped roster row (team=%s, player=%s, position=%s, season=%s, week=%s)",
                            team_label,
                            player_label,
                            position,
                            season,
                            week,
                        )
            if not remaining:
                messages.append("No roster records eligible for insert after FK validation")
                if skipped or db_skipped:
                    skipped_count = len(skipped) + len(db_skipped)
                    messages.append(f"Skipped {skipped_count} rows with unknown players")
                return PipelineResult(True, processed_total, messages=messages)
            written = len(getattr(response, "data", []) or []) if response is not None else len(remaining)
            if skipped or db_skipped:
                skipped_count = len(skipped) + len(db_skipped)
                messages.append(f"Skipped {skipped_count} rows with unknown players")
            return PipelineResult(True, processed_total, written=written, messages=messages)
        except Exception as exc:  # pragma: no cover
            self.logger.exception("Failed to write roster records")
            return PipelineResult(False, processed_total, error=str(exc))


def build_rosters_pipeline(writer=None) -> DatasetPipeline:
    return DatasetPipeline(
        name="rosters",
        fetcher=_fetch_rosters,
        transformer_factory=RosterDataTransformer,
        writer=writer or RosterSupabaseWriter(
            table_name="rosters",
            clear_column="player",
            clear_guard="",
        ),
    )


class RostersDataLoader(PipelineLoader):
    """Expose the legacy loader API on top of the new pipeline."""

    def __init__(self, pipeline: Optional[DatasetPipeline] = None) -> None:
        super().__init__(pipeline or build_rosters_pipeline())
