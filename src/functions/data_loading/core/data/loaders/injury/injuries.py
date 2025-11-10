"""Pipeline-backed loader for NFL injury reports."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .....core.data.fetch import fetch_injury_data
from .....core.data.transformers.injury import InjuryDataTransformer
from .....core.pipelines import DatasetPipeline, PipelineLoader, PipelineResult
from .....core.pipelines.writers import SupabaseWriter
from .....core.utils.logging import get_logger

logger = get_logger(__name__)


def build_injuries_pipeline(writer: Optional[SupabaseWriter] = None) -> DatasetPipeline:
    """Construct a dataset pipeline for injury reports."""

    def _fetch(**params: Any):
        season = params.get("season")
        week = params.get("week")
        if season is None or week is None:
            raise ValueError("Both `season` and `week` parameters are required for injuries")
        return fetch_injury_data(
            season=season,
            week=week,
            season_type=params.get("season_type", "reg"),
        )

    return DatasetPipeline(
        name="injuries",
        fetcher=_fetch,
        transformer_factory=InjuryDataTransformer,
        writer=writer or InjurySupabaseWriter(),
    )


class InjuriesDataLoader(PipelineLoader):
    """Expose the legacy loader interface for injury ingestion."""

    def __init__(self, pipeline: Optional[DatasetPipeline] = None) -> None:
        super().__init__(pipeline or build_injuries_pipeline())


class InjurySupabaseWriter(SupabaseWriter):
    """Writer that resolves player identifiers before persisting injuries."""

    allowed_columns = {
        "season",
        "week",
        "season_type",
        "team_abbr",
        "player_id",
        "player_name",
        "injury",
        "practice_status",
        "game_status",
        "last_update",
        "version",
        "is_current",
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        supabase_client = kwargs.pop("supabase_client", None)
        conflict_columns = kwargs.pop("conflict_columns", None)  # No conflict resolution with versioning
        clear_column = kwargs.pop("clear_column", None)
        clear_guard = kwargs.pop("clear_guard", "")
        super().__init__(
            "injuries",
            conflict_columns=conflict_columns,
            clear_column=clear_column,
            clear_guard=clear_guard,
            supabase_client=supabase_client,
        )
        self._player_index: Optional[Dict[str, List[Dict[str, Optional[str]]]]] = None

    def write(self, records: List[Dict[str, Any]], *, clear: bool = False) -> PipelineResult:
        processed_total = len(records)
        
        # Note: clear is not supported for injuries table
        # Injuries are automatically updated via upsert on (team_abbr, player_id)
        if clear:
            self.logger.warning(
                "Clear flag ignored for injuries table. "
                "Records are automatically updated via upsert on (team_abbr, player_id)."
            )
        
        try:
            prepared, skipped = self._prepare_records(records)
            messages: List[str] = []

            if not prepared:
                if skipped:
                    messages.append(
                        f"Skipped {len(skipped)} injury records due to unresolved player IDs"
                    )
                return PipelineResult(True, processed_total, messages=messages)

            self._ensure_versioning_columns()

            version_map = self._apply_versioning(prepared)

            response = self._perform_write(prepared)
            error = getattr(response, "error", None)
            if error:
                self.logger.error("Supabase error while writing injuries: %s", error)
                return PipelineResult(False, processed_total, error=str(error))

            self._mark_previous_versions_inactive(version_map)

            written = len(getattr(response, "data", []) or [])
            if not written:
                written = len(prepared)

            if skipped:
                messages.append(
                    f"Skipped {len(skipped)} injury records due to unresolved player IDs"
                )
            if messages:
                return PipelineResult(True, processed_total, written=written, messages=messages)
            return PipelineResult(True, processed_total, written=written)
        except Exception as exc:  # pragma: no cover - defensive safety net
            self.logger.exception("Failed to persist injury data")
            return PipelineResult(False, processed_total, error=str(exc))

    def _prepare_records(
        self, records: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        prepared: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        index = self._load_player_index()

        for record in records:
            # Extract season, week, season_type for versioning
            season = record.get("season")
            week = record.get("week")
            season_type = _clean_str(record.get("season_type"))
            
            if not season or not week or not season_type:
                self.logger.warning(
                    "Missing season/week/season_type for record: %s", record
                )
                skipped.append(record)
                continue
            
            team_abbr = _clean_str(record.get("team_abbr"))
            player_name = _clean_str(record.get("player_name"))
            if not team_abbr or not player_name:
                skipped.append(record)
                continue

            player_id = _clean_str(record.get("player_id") or record.get("source_player_id"))
            if not player_id:
                player_id = self._resolve_player_id(player_name, team_abbr, index)

            if not player_id:
                self.logger.warning(
                    "Unable to resolve player '%s' for team %s", player_name, team_abbr
                )
                skipped.append(record)
                continue

            last_update = record.get("last_update")
            if isinstance(last_update, str) and not last_update.strip():
                last_update = None
            if last_update is None:
                last_update = datetime.now(timezone.utc).isoformat()

            prepared.append(
                {
                    "season": season,
                    "week": week,
                    "season_type": season_type.upper(),  # Normalize to uppercase
                    "team_abbr": team_abbr,
                    "player_id": player_id,
                    "player_name": player_name,
                    "injury": record.get("injury"),
                    "practice_status": record.get("practice_status"),
                    "game_status": record.get("game_status"),
                    "last_update": last_update,
                }
            )

        return prepared, skipped

    def _apply_versioning(self, records: List[Dict[str, Any]]) -> Dict[Tuple[Any, Any, str], int]:
        """Assign a monotonically increasing version per (season, week, season_type)."""

        if not records:
            return {}

        version_map = self._fetch_next_versions(records)

        for record in records:
            scope = (record["season"], record["week"], record["season_type"])
            record["version"] = version_map[scope]
            record["is_current"] = True

        return version_map

    def _ensure_versioning_columns(self) -> None:
        """Validate that the injuries table exposes the versioning columns.

        Raises a descriptive error when the Supabase schema has not yet been
        updated so operators understand how to resolve the issue instead of the
        pipeline failing with an opaque column-missing error.
        """

        hint = (
            "The injuries table must include an integer `version` column and a "
            "boolean `is_current` column (defaulting to true)."
        )

        try:
            response = (
                self.client.table("injuries")
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
            "Unexpected error while validating injury versioning columns: %s",
            message,
        )

    def _fetch_next_versions(self, records: List[Dict[str, Any]]) -> Dict[Tuple[Any, Any, str], int]:
        scopes = {
            (record["season"], record["week"], record["season_type"])
            for record in records
        }
        version_map: Dict[Tuple[Any, Any, str], int] = {}

        for season, week, season_type in scopes:
            try:
                response = (
                    self.client.table("injuries")
                    .select("version")
                    .eq("season", season)
                    .eq("week", week)
                    .eq("season_type", season_type)
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
                            "Unexpected version value '%s' for %s/%s/%s; defaulting to 0",
                            raw_value,
                            season,
                            week,
                            season_type,
                        )
                        current_version = 0
                version_map[(season, week, season_type)] = current_version + 1
            except Exception as exc:  # pragma: no cover - guard Supabase errors
                self.logger.exception(
                    "Unable to resolve next version for injuries %s/%s/%s", season, week, season_type
                )
                raise RuntimeError("Failed to calculate injury version") from exc

        return version_map

    def _mark_previous_versions_inactive(
        self, version_map: Dict[Tuple[Any, Any, str], int]
    ) -> None:
        for (season, week, season_type), version in version_map.items():
            try:
                response = (
                    self.client.table("injuries")
                    .update({"is_current": False})
                    .eq("season", season)
                    .eq("week", week)
                    .eq("season_type", season_type)
                    .lt("version", version)
                    .execute()
                )
                error = getattr(response, "error", None)
                if error:
                    self.logger.warning(
                        "Failed to mark stale injuries inactive for %s/%s/%s: %s",
                        season,
                        week,
                        season_type,
                        error,
                    )
            except Exception:  # pragma: no cover - defensive logging
                self.logger.exception(
                    "Error while marking stale injuries inactive for %s/%s/%s",
                    season,
                    week,
                    season_type,
                )

    def _load_player_index(self) -> Dict[str, List[Dict[str, Optional[str]]]]:
        if self._player_index is not None:
            return self._player_index

        index: Dict[str, List[Dict[str, Optional[str]]]] = {}
        page_size = 1000
        offset = 0

        while True:
            response = (
                self.client.table("players")
                .select("player_id, display_name, first_name, last_name, latest_team")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            data = getattr(response, "data", None) or []
            if not data:
                break

            for row in data:
                entry = {
                    "player_id": _clean_str(row.get("player_id")),
                    "display_name": _clean_str(row.get("display_name")),
                    "first_name": _clean_str(row.get("first_name")),
                    "last_name": _clean_str(row.get("last_name")),
                    "latest_team": _clean_str(row.get("latest_team")),
                }
                if not entry["player_id"]:
                    continue
                for key in self._iter_player_keys(entry):
                    index.setdefault(key, []).append(entry)

            if len(data) < page_size:
                break
            offset += page_size

        self._player_index = index
        self.logger.debug("Loaded %d injury player name keys", len(index))
        return index

    def _iter_player_keys(self, entry: Dict[str, Optional[str]]) -> Iterable[str]:
        names: List[str] = []
        if entry.get("display_name"):
            names.append(entry["display_name"] or "")
        if entry.get("first_name") and entry.get("last_name"):
            names.append(f"{entry['first_name']} {entry['last_name']}")
            names.append(f"{entry['last_name']}, {entry['first_name']}")
        seen: set[str] = set()
        for name in names:
            key = self._normalise_key(name)
            if key and key not in seen:
                seen.add(key)
                yield key

    def _resolve_player_id(
        self,
        player_name: str,
        team_abbr: str,
        index: Dict[str, List[Dict[str, Optional[str]]]],
    ) -> Optional[str]:
        key = self._normalise_key(player_name)
        if not key:
            return None
        candidates = list(index.get(key, []))
        if not candidates:
            return None

        team_abbr_upper = team_abbr.upper()
        team_matches = [
            candidate
            for candidate in candidates
            if (candidate.get("latest_team") or "").upper() == team_abbr_upper
        ]
        if len(team_matches) == 1:
            return team_matches[0]["player_id"]
        if team_matches:
            candidates = team_matches

        unique_ids = {candidate["player_id"] for candidate in candidates if candidate.get("player_id")}
        if len(unique_ids) == 1:
            return next(iter(unique_ids))
        if unique_ids:
            chosen = next(iter(unique_ids))
            self.logger.warning(
                "Multiple matching players for %s; defaulting to %s", player_name, chosen
            )
            return chosen
        return None

    @staticmethod
    def _normalise_key(value: str) -> Optional[str]:
        if not value:
            return None
        return re.sub(r"[^a-z0-9]", "", value.lower()) or None


def _clean_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
