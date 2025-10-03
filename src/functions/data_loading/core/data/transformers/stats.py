"""Transformers for advanced statistics datasets."""

from __future__ import annotations

from typing import Any, Dict, Optional

from math import isnan

from ....core.data.transform import BaseDataTransformer


class NextGenStatsDataTransformer(BaseDataTransformer):
    """Transform NextGenStats (NGS) data."""

    _ID_FIELDS = (
        "player_id",
        "player_gsis_id",
        "gsis_id",
        "nflverse_player_id",
        "nflverse_id",
        "pfr_id",
    )

    def __init__(self, stat_type: Optional[str] = None) -> None:
        super().__init__()
        self.stat_type = stat_type

    def sanitize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        player_id = self._resolve_player_id(record)
        season = self._coerce_int(record.get("season"))
        week = self._coerce_int(record.get("week"))

        cleaned: Dict[str, Any] = {}
        for key, value in record.items():
            cleaned[key] = self._normalise_value(value)

        cleaned.update(
            {
                "player_id": player_id,
                "season": season,
                "week": week,
                "stat_type": self.stat_type,
            }
        )
        return cleaned

    def validate_record(self, record: Dict[str, Any]) -> bool:
        player_id = record.get("player_id")
        if not player_id:
            return False

        season = record.get("season")
        week = record.get("week")
        return season is not None and week is not None

    @classmethod
    def _resolve_player_id(cls, record: Dict[str, Any]) -> Optional[str]:
        for field in cls._ID_FIELDS:
            candidate = record.get(field)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return None

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
                return int(stripped)
            except ValueError:
                return None
        return None

    @staticmethod
    def _normalise_value(value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class FTNDataTransformer(BaseDataTransformer):
    """Transform FTN play-level data into serialisable records."""

    required_fields = ["ftn_play_id", "season", "week"]

    def sanitize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        sanitized: Dict[str, Any] = {
            "ftn_play_id": record.get("ftn_play_id"),
            "ftn_game_id": record.get("ftn_game_id"),
            "nflverse_game_id": record.get("nflverse_game_id"),
            "season": record.get("season"),
            "week": record.get("week"),
        }

        for key, value in record.items():
            if key not in sanitized:
                sanitized[key] = self._normalise_value(value)

        for key in list(sanitized.keys()):
            sanitized[key] = self._normalise_value(sanitized[key])

        return sanitized

    @staticmethod
    def _normalise_value(value: Any) -> Any:
        if hasattr(value, "isoformat"):
            try:
                return value.isoformat()
            except TypeError:
                pass
        return value
