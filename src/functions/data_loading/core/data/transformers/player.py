"""Transformers for player-centric datasets."""

from __future__ import annotations

from datetime import datetime, timezone
from math import isnan
from typing import Any, Dict, List, Optional

from ....core.data.transform import BaseDataTransformer


class PlayerDataTransformer(BaseDataTransformer):
    """Transform player metadata into database-ready records."""

    required_fields = ["player_id", "display_name"]

    def sanitize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        def _coerce_int(value: Any) -> Optional[int]:
            if value in (None, "", "nan"):
                return None
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return None

        def _coerce_iso(value: Any) -> Optional[str]:
            if value is None or value == "":
                return None
            if isinstance(value, datetime):
                return value.isoformat()
            return str(value)

        def _clean_str(value: Any) -> Optional[str]:
            if value is None:
                return None
            text = str(value).strip()
            return text or None

        player_id = (
            record.get("player_id")
            or record.get("gsis_id")
            or record.get("sportradar_id")
            or record.get("pfr_id")
            or record.get("espn_id")
            or record.get("yahoo_id")
            or record.get("rotowire_id")
        )

        first_name = _clean_str(record.get("first_name") or record.get("common_first_name"))
        last_name = _clean_str(record.get("last_name"))
        display_name = (
            _clean_str(record.get("display_name"))
            or _clean_str(record.get("player_name"))
            or _clean_str(record.get("name"))
        )
        if not display_name and (first_name or last_name):
            display_name = " ".join(filter(None, [first_name, last_name])) or None

        short_name = (
            _clean_str(record.get("short_name"))
            or _clean_str(record.get("common_name"))
            or (first_name[:10] if first_name else None)
        )

        football_name = (
            _clean_str(record.get("football_name"))
            or display_name
        )

        birth_date = _coerce_iso(record.get("birth_date") or record.get("dob"))
        updated_at = _coerce_iso(
            record.get("last_modified_date")
            or record.get("metadata_last_updated")
            or datetime.now(timezone.utc)
        )

        jersey_raw = record.get("jersey_number")
        jersey_number = None
        if jersey_raw not in (None, ""):
            jersey_int = _coerce_int(jersey_raw)
            jersey_number = str(jersey_int) if jersey_int is not None else str(jersey_raw).strip()

        latest_team = (
            record.get("recent_team")
            or record.get("team")
            or record.get("last_team")
        )
        latest_team = _clean_str(latest_team)
        if latest_team:
            latest_team = latest_team.upper()

        draft_team = _clean_str(record.get("draft_team") or record.get("draft_club"))
        if draft_team:
            draft_team = draft_team.upper()

        status_raw = _clean_str(record.get("status"))
        status = status_raw.lower() if status_raw else None

        payload = {
            "player_id": player_id,
            "birth_date": birth_date,
            "height": _coerce_int(
                record.get("height")
                or record.get("height_in")
                or record.get("height_inches")
            ),
            "weight": _coerce_int(record.get("weight")),
            "college_name": _clean_str(record.get("college_name") or record.get("college")),
            "position": _clean_str(record.get("position")),
            "rookie_season": _coerce_int(record.get("rookie_year") or record.get("first_season")),
            "last_season": _coerce_int(record.get("last_season") or record.get("last_active_season")),
            "display_name": display_name,
            "common_first_name": _clean_str(record.get("common_first_name")) or first_name,
            "first_name": first_name,
            "last_name": last_name,
            "short_name": short_name,
            "football_name": football_name,
            "suffix": _clean_str(record.get("suffix") or record.get("name_suffix")),
            "position_group": _clean_str(record.get("position_group")),
            "headshot": _clean_str(record.get("headshot") or record.get("headshot_url")),
            "college_conference": _clean_str(record.get("college_conference")),
            "jersey_number": jersey_number,
            "status": status,
            "latest_team": latest_team,
            "years_of_experience": _coerce_int(record.get("years_of_experience") or record.get("experience")),
            "draft_year": _coerce_int(record.get("draft_year")),
            "draft_round": _coerce_int(record.get("draft_round")),
            "draft_pick": _coerce_int(record.get("draft_pick")),
            "draft_team": draft_team,
            "updated_at": updated_at,
            "sleeper_id": _clean_str(record.get("sleeper_id")),
            "espn_id": _clean_str(record.get("espn_id") or record.get("espn")),
            "pfr_id": _clean_str(record.get("pfr_id") or record.get("pfr")),
        }

        return payload


class PlayerWeeklyStatsDataTransformer(BaseDataTransformer):
    """Transform weekly player statistics."""

    required_fields = ["player_id", "season", "week"]

    def sanitize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = {
            "player_id": record.get("player_id") or record.get("pfr_id"),
            "season": record.get("season"),
            "week": record.get("week"),
        }
        for key, value in record.items():
            if isinstance(value, (int, float)) and key not in sanitized:
                sanitized[key] = value
        return sanitized


class PfrPlayerSeasonDataTransformer(BaseDataTransformer):
    """Normalise PFR player-season records for downstream payloads."""

    required_fields = ["player_id", "season", "week"]

    _BASE_FIELDS = {
        "game_id",
        "pfr_game_id",
        "season",
        "week",
        "game_type",
        "team",
        "opponent",
        "pfr_player_name",
        "pfr_player_id",
        "stat_type",
    }

    def sanitize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        player_id = self._clean_str(record.get("pfr_player_id") or record.get("player_id"))
        player_name = self._clean_str(record.get("pfr_player_name") or record.get("player_name"))
        season = self._coerce_int(record.get("season"))
        week = self._coerce_int(record.get("week"))

        cleaned: Dict[str, Any] = {
            "player_id": player_id,
            "player_name": player_name,
            "season": season,
            "week": week,
            "team": self._clean_str(record.get("team")),
            "opponent": self._clean_str(record.get("opponent")),
            "game_id": self._clean_str(record.get("game_id")),
            "pfr_game_id": self._clean_str(record.get("pfr_game_id")),
            "game_type": self._clean_str(record.get("game_type")),
            "stat_type": self._clean_str(record.get("stat_type")),
        }

        metrics: Dict[str, Any] = {}
        for key, value in record.items():
            if key in self._BASE_FIELDS:
                continue
            normalised_value = self._normalise_metric(value)
            if normalised_value is not None:
                metrics[key] = normalised_value

        cleaned["metrics"] = metrics
        return cleaned

    def deduplicate_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        unique: Dict[tuple[Any, Any, Any, Any], Dict[str, Any]] = {}
        for record in records:
            key = (
                record.get("player_id"),
                record.get("season"),
                record.get("week"),
                record.get("stat_type"),
            )
            unique[key] = record
        return list(unique.values())

    @staticmethod
    def _clean_str(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int,)):
            return value
        if isinstance(value, float):
            if isnan(value):
                return None
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return int(float(stripped))
            except ValueError:
                return None
        return None

    @staticmethod
    def _normalise_metric(value: Any) -> Optional[Any]:
        if value is None:
            return None
        if isinstance(value, float) and isnan(value):
            return None
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            text = value.strip()
            return text or None
        return None


class SnapCountsDataTransformer(BaseDataTransformer):
    """Transform snap counts data."""

    required_fields = ["player_id", "season", "week"]

    def sanitize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "player_id": record.get("player_id") or record.get("pfr_id"),
            "season": record.get("season"),
            "week": record.get("week"),
            "offensive_snaps": record.get("offense_snaps"),
            "defensive_snaps": record.get("defense_snaps"),
            "special_teams_snaps": record.get("special_teams_snaps"),
        }


class SnapCountsGameDataTransformer(BaseDataTransformer):
    """Normalise snap count records at the player-game grain."""

    required_fields = ["player_id", "game_id"]

    def sanitize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        player_id = self._clean_str(
            record.get("pfr_player_id")
            or record.get("player_id")
            or record.get("pfr_id")
        )

        cleaned: Dict[str, Any] = {
            "player_id": player_id,
            "player_name": self._clean_str(record.get("player")),
            "game_id": self._clean_str(record.get("game_id")),
            "pfr_game_id": self._clean_str(record.get("pfr_game_id")),
            "season": self._coerce_int(record.get("season")),
            "week": self._coerce_int(record.get("week")),
            "game_type": self._clean_str(record.get("game_type")),
            "team": self._clean_str(record.get("team")),
            "opponent": self._clean_str(record.get("opponent")),
            "offensive_snaps": self._coerce_float(record.get("offense_snaps")),
            "offensive_pct": self._coerce_float(record.get("offense_pct")),
            "defensive_snaps": self._coerce_float(record.get("defense_snaps")),
            "defensive_pct": self._coerce_float(record.get("defense_pct")),
            "special_teams_snaps": self._coerce_float(record.get("st_snaps")),
            "special_teams_pct": self._coerce_float(record.get("st_pct")),
        }

        return cleaned

    @staticmethod
    def _clean_str(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if isnan(value):
                return None
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return int(float(stripped))
            except ValueError:
                return None
        return None

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            if isinstance(value, float) and isnan(value):
                return None
            return float(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return float(stripped)
            except ValueError:
                return None
        return None


class DepthChartsDataTransformer(BaseDataTransformer):
    """Transform depth chart information."""

    required_fields = ["team", "player_id"]

    def sanitize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        def _clean(value: Any) -> Optional[str]:
            if value is None:
                return None
            if isinstance(value, float) and value != value:
                return None
            text = str(value).strip()
            if not text or text.lower() == "nan":
                return None
            return text

        def _upper(value: Optional[str]) -> Optional[str]:
            return value.upper() if value else None

        def _find_value(*include: str, exclude: tuple[str, ...] = ()) -> Optional[Any]:
            normalized_include = tuple(term.lower() for term in include)
            normalized_exclude = tuple(term.lower() for term in exclude)
            for key, value in record.items():
                key_lower = key.lower()
                if normalized_exclude and any(term in key_lower for term in normalized_exclude):
                    continue
                if all(term in key_lower for term in normalized_include):
                    return value
            return None

        def _normalize_rank(value: Optional[str]) -> Optional[str]:
            raw = _clean(value)
            if raw is None:
                return None
            try:
                numeric = float(raw)
            except (TypeError, ValueError):
                digits = "".join(ch for ch in raw if ch.isdigit())
                if digits:
                    return digits
                return None
            if numeric.is_integer():
                return str(int(numeric))
            return str(numeric)

        player_id = (
            _clean(record.get("player_id"))
            or _clean(record.get("gsis_id"))
            or _clean(record.get("pfr_id"))
            or _clean(record.get("nfl_id"))
        )

        team = _upper(_clean(record.get("team")))

        pos_group = _clean(
            record.get("position_group")
            or record.get("pos_group")
            or record.get("depth_chart_group")
            or _find_value("position", "group")
            or _find_value("pos", "group")
            or _find_value("unit")
            or _find_value("side", "ball")
        )

        pos_name = _clean(
            record.get("pos_name")
            or record.get("position")
            or record.get("position_name")
            or record.get("position_full")
            or record.get("depth_chart_category")
            or _find_value(
                "position",
                exclude=("group", "abbr", "slot", "rank", "depth", "unit"),
            )
        )

        pos_abbr = _upper(
            _clean(
                record.get("pos_abb")
                or record.get("position_abbr")
                or record.get("position_short")
                or record.get("position_abbreviation")
                or record.get("depth_chart_code")
                or _find_value("abbr")
                or _find_value("position", "code")
            )
        )

        pos_slot = _clean(
            record.get("pos_slot")
            or record.get("depth_chart_position")
            or record.get("position_slot")
            or record.get("position_depth_chart")
            or record.get("position_chart")
            or _find_value("slot")
            or _find_value("depth", "position")
        )

        pos_rank = _normalize_rank(
            record.get("pos_rank")
            or record.get("depth_chart_order")
            or record.get("depth_chart_rank")
            or record.get("position_rank")
            or record.get("position_order")
            or record.get("depth")
            or _find_value("rank")
            or _find_value("order")
            or _find_value("depth")
        )

        player_name = _clean(
            record.get("display_name")
            or record.get("full_name")
            or record.get("player_name")
            or record.get("name")
        )

        if not pos_slot and pos_abbr and pos_rank:
            pos_slot = f"{pos_abbr}{pos_rank}" if pos_rank else pos_abbr

        if not pos_rank and pos_slot:
            digits = "".join(ch for ch in pos_slot if ch.isdigit())
            pos_rank = digits or None

        if not pos_abbr and pos_slot:
            letters = "".join(ch for ch in pos_slot if ch.isalpha())
            pos_abbr = letters.upper() or None

        pos_slot = _upper(pos_slot)

        if not pos_name and pos_abbr:
            pos_name = pos_abbr

        if not pos_group and pos_name:
            pos_group = pos_name

        return {
            "team": team,
            "player_id": player_id,
            "pos_grp": pos_group,
            "pos_name": pos_name,
            "pos_abb": pos_abbr,
            "pos_slot": pos_slot,
            "pos_rank": pos_rank,
            "player_name": player_name,
        }

    def deduplicate_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        unique: Dict[tuple[str, str, Optional[str]], Dict[str, Any]] = {}
        for record in records:
            key = (record.get("team"), record.get("player_id"), record.get("pos_grp"))
            rank_value = record.get("pos_rank")
            try:
                rank_float = float(rank_value) if rank_value is not None else float("inf")
            except (TypeError, ValueError):
                rank_float = float("inf")

            existing = unique.get(key)
            if existing is None:
                unique[key] = {**record, "_rank_score": rank_float}
                continue

            if rank_float < existing.get("_rank_score", float("inf")):
                unique[key] = {**record, "_rank_score": rank_float}

        output = []
        for value in unique.values():
            value.pop("_rank_score", None)
            output.append(value)
        return output


class RosterDataTransformer(BaseDataTransformer):
    """Transform roster data into player roster records."""

    required_fields = ["team", "player"]

    def sanitize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        def _clean_str(value: Any) -> Optional[str]:
            if value is None:
                return None
            text = str(value).strip()
            return text or None

        def _coerce_int(value: Any) -> Optional[int]:
            if value in (None, "", "nan"):
                return None
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return None

        player = (
            record.get("player_id")
            or record.get("gsis_id")
            or record.get("pfr_id")
            or record.get("nfl_id")
        )

        team = _clean_str(record.get("team") or record.get("recent_team"))
        if team:
            team = team.upper()

        dept_chart_position = _clean_str(
            record.get("depth_chart_position")
            or record.get("depth_chart_order")
            or record.get("position")
        )

        if dept_chart_position:
            dept_chart_position = dept_chart_position.upper()

        player_name = _clean_str(
            record.get("display_name")
            or record.get("full_name")
            or record.get("player_name")
            or record.get("name")
        )

        season = _coerce_int(record.get("season"))
        week = _coerce_int(record.get("week"))

        return {
            "team": team,
            "player": player,
            "dept_chart_position": dept_chart_position,
            "season": season,
            "week": week,
            "player_name": player_name,
        }
