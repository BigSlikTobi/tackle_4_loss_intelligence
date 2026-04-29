"""Pipeline-backed loader for team depth charts with versioning support."""

from __future__ import annotations

from collections import defaultdict
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


def _fetch_depth_charts(
    team: Optional[str] = None,
    season: Optional[int] = None,
    week: Optional[int] = None,
    **_: Any,
):
    from nflreadpy import load_depth_charts  # type: ignore

    target_season = int(season) if season is not None else datetime.now().year
    df = load_depth_charts(seasons=target_season)
    df = df.to_pandas() if hasattr(df, "to_pandas") else pd.DataFrame(df)

    # nflreadpy doesn't always include `season`; stamp it.
    if "season" not in df.columns:
        df["season"] = target_season
    df["season"] = pd.to_numeric(df["season"], errors="coerce").astype("Int64")

    if team:
        df = df[df["team"].str.upper() == team.upper()]
        df = _filter_latest(df)
    else:
        # Group-then-filter without groupby.apply (avoids pandas FutureWarning).
        df = pd.concat(
            [_filter_latest(group) for _, group in df.groupby("team", sort=False)],
            ignore_index=True,
        )

    # Stamp the snapshot week. nflreadpy returns "current as of fetch"; the
    # `week` arg is a label used by the writer's per-(season, week, team)
    # versioning, not a filter on the source.
    snapshot_week = int(week) if week is not None else 0
    df["week"] = snapshot_week
    logger.info(
        "Tagging depth chart snapshot for season=%s week=%s (%d teams)",
        target_season,
        snapshot_week,
        df["team"].nunique() if "team" in df.columns else 0,
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
        # `clear` is intentionally ignored: depth charts are versioned per
        # (season, week, team), so prior versions are flagged is_current=false
        # rather than deleted. The CLI no longer forwards clear here.
        del clear

        try:
            prepared, skipped, summary_rows = self._prepare_records(records)
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
            messages.extend(self._format_team_summary(summary_rows, version_map))
            return PipelineResult(True, processed_total, written=written, messages=messages)
        except Exception as exc:  # pragma: no cover
            self.logger.exception("Failed to write depth chart records")
            return PipelineResult(False, processed_total, error=str(exc))

    def _prepare_records(
        self, records: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Tuple[str, str, str, str]]]:
        """Validate references and return (prepared, skipped, summary_rows).

        ``summary_rows`` is a list of (team, pos_abb, pos_rank, player_name)
        tuples for records that survived validation; the writer uses it to
        produce the per-team starter rollup printed after a successful run.
        """

        prepared: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        summary_rows: List[Tuple[str, str, str, str]] = []

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

            if season is None or season == "":
                player_label = rec.get("player_name") or player_id or "<unknown>"
                self.logger.warning(
                    "Skipping depth chart entry for %s - missing season", player_label
                )
                skipped.append(rec)
                continue

            if week is None or week == "":
                rec["week"] = 0
                week = 0

            missing_reason: Optional[str] = None
            if not player_id or player_id not in known_players:
                missing_reason = "player"
            elif not team or team not in known_teams:
                missing_reason = "team"

            if missing_reason:
                player_label = rec.get("player_name") or player_id or "<unknown>"
                team_label = team or "<no team>"
                self.logger.warning(
                    "Skipping depth chart entry for %s on %s due to missing %s record",
                    player_label,
                    team_label,
                    missing_reason,
                )
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(
                        "Skipped row (team=%s, player=%s, slot=%s, rank=%s, season=%s, week=%s)",
                        team_label,
                        player_label,
                        rec.get("pos_slot"),
                        rec.get("pos_rank"),
                        season,
                        week,
                    )
                skipped.append(rec)
                continue

            summary_rows.append(
                (
                    str(team),
                    str(rec.get("pos_abb") or ""),
                    str(rec.get("pos_rank") or ""),
                    str(rec.get("player_name") or player_id or "?"),
                )
            )
            prepared.append({k: v for k, v in rec.items() if k in self.allowed_columns})

        return prepared, skipped, summary_rows

    @staticmethod
    def _format_team_summary(
        summary_rows: List[Tuple[str, str, str, str]],
        version_map: Dict[Tuple[Any, Any, Any], int],
    ) -> List[str]:
        """Build a human-readable per-team rollup of starters and entry counts."""

        if not summary_rows:
            return []

        # Group entries per team: total count + starter at key positions.
        starter_positions = ("QB", "RB", "WR", "TE")
        per_team: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "starters": {}}
        )
        for team, pos_abb, pos_rank, player_name in summary_rows:
            stats = per_team[team]
            stats["count"] += 1
            if pos_rank == "1" and pos_abb in starter_positions:
                stats["starters"].setdefault(pos_abb, player_name)

        version_by_team = {
            team: version for (_season, _week, team), version in version_map.items()
        }

        lines: List[str] = [
            f"Loaded {len(per_team)} team(s), {len(summary_rows)} entries:"
        ]
        for team in sorted(per_team):
            stats = per_team[team]
            starters = stats["starters"]
            cells = [
                f"{pos}1 {starters[pos]}" for pos in starter_positions if pos in starters
            ]
            version = version_by_team.get(team)
            version_tag = f" v{version}" if version is not None else ""
            cells_str = "  ".join(cells) if cells else "(no rank-1 entries)"
            lines.append(f"  {team:<4}{version_tag:<4} {cells_str}  ({stats['count']} entries)")
        return lines

    def _apply_versioning(self, records: List[Dict[str, Any]]) -> Dict[Tuple[Any, Any, Any], int]:
        """Assign a monotonically increasing version per (season, week, team)."""

        if not records:
            return {}

        version_map = self._fetch_next_versions(records)

        for record in records:
            scope = (record["season"], record["week"], record["team"])
            record["version"] = version_map[scope]
            record["is_current"] = True

        return version_map

    def _ensure_versioning_columns(self) -> None:
        """Validate that the depth_charts table exposes the versioning columns.

        Cached on the instance so a single writer doesn't probe the schema on
        every call (writer instances are short-lived; one probe per CLI run is
        the goal).
        """

        if getattr(self, "_versioning_columns_verified", False):
            return

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
        if error:
            message = str(error)
            if "version" in message or "is_current" in message:
                raise RuntimeError(hint)
            self.logger.warning(
                "Unexpected error while validating depth chart versioning columns: %s",
                message,
            )

        self._versioning_columns_verified = True

    def _fetch_next_versions(
        self, records: List[Dict[str, Any]]
    ) -> Dict[Tuple[Any, Any, Any], int]:
        """Compute next version per (season, week, team) using a single round trip.

        Depth-chart loads typically span ~32 teams within one (season, week);
        the previous implementation issued one SELECT per team. This version
        groups scopes by (season, week), runs a single ``in_("team", teams)``
        query per group, and resolves the per-team max client-side.
        """

        scopes = {
            (record["season"], record["week"], record["team"])
            for record in records
            if record.get("season") is not None
            and record.get("week") is not None
            and record.get("team")
        }
        if not scopes:
            return {}

        teams_by_sw: Dict[Tuple[Any, Any], Set[str]] = defaultdict(set)
        for season, week, team in scopes:
            teams_by_sw[(season, week)].add(team)

        version_map: Dict[Tuple[Any, Any, Any], int] = {}
        for (season, week), teams in teams_by_sw.items():
            max_per_team: Dict[str, int] = {team: 0 for team in teams}
            try:
                response = (
                    self.client.table("depth_charts")
                    .select("team,version")
                    .eq("season", season)
                    .eq("week", week)
                    .in_("team", sorted(teams))
                    .execute()
                )
            except Exception as exc:  # pragma: no cover - guard Supabase errors
                self.logger.exception(
                    "Unable to resolve next versions for depth charts %s/%s", season, week
                )
                raise RuntimeError("Failed to calculate depth chart version") from exc

            for row in getattr(response, "data", None) or []:
                team_val = row.get("team")
                if team_val not in max_per_team:
                    continue
                try:
                    candidate = int(row.get("version") or 0)
                except (TypeError, ValueError):
                    self.logger.warning(
                        "Unexpected version '%s' for %s/%s/%s; treating as 0",
                        row.get("version"),
                        season,
                        week,
                        team_val,
                    )
                    candidate = 0
                if candidate > max_per_team[team_val]:
                    max_per_team[team_val] = candidate

            for team, current in max_per_team.items():
                version_map[(season, week, team)] = current + 1

        return version_map

    def _mark_previous_versions_inactive(
        self, version_map: Dict[Tuple[Any, Any, Any], int]
    ) -> None:
        """Flag prior versions inactive in one UPDATE per (season, week) group.

        All teams within the same (season, week) get bumped to the same version
        in a single load (each team's first scope was 1; subsequent reloads
        increment all by 1). When that holds, we can use ``.in_("team", ...)``
        with the shared ``.lt("version", new_version)`` predicate to do it in
        one round trip per group instead of one per team.
        """

        if not version_map:
            return

        groups: Dict[Tuple[Any, Any, int], Set[str]] = defaultdict(set)
        for (season, week, team), version in version_map.items():
            groups[(season, week, version)].add(team)

        for (season, week, version), teams in groups.items():
            try:
                response = (
                    self.client.table("depth_charts")
                    .update({"is_current": False})
                    .eq("season", season)
                    .eq("week", week)
                    .in_("team", sorted(teams))
                    .lt("version", version)
                    .execute()
                )
                error = getattr(response, "error", None)
                if error:
                    self.logger.warning(
                        "Failed to mark stale depth charts inactive for %s/%s (v<%s, %d teams): %s",
                        season,
                        week,
                        version,
                        len(teams),
                        error,
                    )
            except Exception:  # pragma: no cover - defensive logging
                self.logger.exception(
                    "Error while marking stale depth charts inactive for %s/%s (v<%s)",
                    season,
                    week,
                    version,
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
