"""Transformers for game and play datasets."""

from __future__ import annotations

from datetime import datetime
import math
from typing import Any, Dict

from ....core.data.transform import BaseDataTransformer


class GameDataTransformer(BaseDataTransformer):
    """Transform schedule data into game records."""

    required_fields = ["game_id", "season", "week"]

    def sanitize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        def _clean_str(value: Any) -> Any:
            if value is None:
                return None
            text = str(value).strip()
            return text or None

        def _clean_upper(value: Any) -> Any:
            text = _clean_str(value)
            return text.upper() if text else None

        def _coerce_float(value: Any) -> Any:
            if value in (None, "", "nan"):
                return None
            if isinstance(value, float) and math.isnan(value):
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                try:
                    return float(str(value))
                except (TypeError, ValueError):
                    return None

        def _coerce_int(value: Any) -> Any:
            if value in (None, "", "nan"):
                return None
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return None

        def _coerce_iso(value: Any) -> Any:
            if value is None:
                return None
            if hasattr(value, "isoformat"):
                try:
                    return value.isoformat()
                except TypeError:
                    pass
            return _clean_str(value)

        game_id = _clean_str(record.get("game_id") or record.get("game_key"))
        season = _coerce_int(record.get("season") or record.get("season_year"))
        week = _coerce_int(record.get("week") or record.get("game_week"))

        gameday = (
            _coerce_iso(record.get("gameday"))
            or _coerce_iso(record.get("game_date"))
            or _coerce_iso(record.get("start_time"))
        )

        gametime = _clean_str(
            record.get("gametime")
            or record.get("game_time")
            or record.get("kickoff_time")
        )

        weekday = _clean_str(
            record.get("weekday")
            or record.get("day_of_week")
            or record.get("weekday_name")
        )

        if not weekday and gameday:
            try:
                from datetime import datetime

                weekday = datetime.fromisoformat(gameday).strftime("%A")
            except (ValueError, TypeError):
                weekday = None

        overtime_value = record.get("overtime")
        if overtime_value in (None, "", "nan"):
            overtime_value = record.get("overtime_periods")

        payload = {
            "game_id": game_id,
            "season": season,
            "game_type": _clean_upper(record.get("game_type") or record.get("season_type")),
            "week": week,
            "gameday": gameday,
            "weekday": weekday,
            "gametime": gametime,
            "away_team": _clean_upper(record.get("away_team")),
            "away_score": _coerce_float(record.get("away_score")),
            "home_team": _clean_upper(record.get("home_team")),
            "home_score": _coerce_float(record.get("home_score")),
            "location": _clean_str(record.get("location") or record.get("site")),
            "result": _coerce_float(record.get("result")),
            "total": _coerce_float(record.get("total")),
            "overtime": _coerce_float(overtime_value),
            "pfr": _clean_str(record.get("pfr")),
            "pff": _clean_str(record.get("pff")),
            "ftn": _clean_str(record.get("ftn")),
            "roof": _clean_str(record.get("roof")),
            "surface": _clean_str(record.get("surface")),
            "temp": _coerce_float(record.get("temp") or record.get("temperature")),
            "wind": _coerce_float(record.get("wind") or record.get("wind_speed")),
            "referee": _clean_str(record.get("referee")),
            "stadium": _clean_str(record.get("stadium") or record.get("venue")),
        }

        return payload


class PlayByPlayDataTransformer(BaseDataTransformer):
    """Transform play-by-play data into simplified play records."""

    required_fields = ["play_id", "game_id", "season", "week"]

    def sanitize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        sanitized: Dict[str, Any] = {
            "play_id": record.get("play_id"),
            "game_id": record.get("game_id"),
            "season": record.get("season"),
            "week": record.get("week"),
            "posteam": record.get("posteam"),
            "defteam": record.get("defteam"),
            "play_type": record.get("play_type"),
            "yards_gained": record.get("yards_gained"),
            "down": record.get("down"),
            "distance": record.get("ydstogo"),
            "yardline_100": record.get("yardline_100"),
            "game_date": self._normalise_value(record.get("game_date")),
            "clock": record.get("time"),
            "description": record.get("desc") or record.get("play_description"),
            # Scoring indicators
            "touchdown": record.get("touchdown"),
            "safety": record.get("safety"),
        }

        participant_keys = [
            "passer_player_id",
            "receiver_player_id",
            "rusher_player_id",
            "td_player_id",
            "interception_player_id",
            "punt_returner_player_id",
            "kickoff_returner_player_id",
            "kicker_player_id",  # Include kicker for field goals and extra points
            "fumbled_1_player_id",
            "fumbled_2_player_id",
            "tackle_for_loss_1_player_id",
            "tackle_for_loss_2_player_id",
            "sack_player_id",
        ]

        participant_ids = []
        for key in participant_keys:
            value = record.get(key)
            sanitized[key] = value
            if value:
                participant_ids.append(value)

        if participant_ids:
            deduped = tuple(dict.fromkeys(participant_ids))
            sanitized["player_ids"] = deduped
            sanitized["primary_player_id"] = deduped[0]
        else:
            sanitized["player_ids"] = tuple()
            sanitized["primary_player_id"] = None

        priority_keys = [
            "td_player_id",
            "receiver_player_id",
            "rusher_player_id",
            "passer_player_id",
            "interception_player_id",
            "sack_player_id",
        ]

        selected_player_id = None
        for key in priority_keys:
            value = sanitized.get(key)
            if value:
                selected_player_id = value
                break

        if selected_player_id is None and participant_ids:
            selected_player_id = participant_ids[0]

        sanitized["player_id"] = selected_player_id

        return sanitized

    @staticmethod
    def _normalise_value(value: Any) -> Any:
        if hasattr(value, "isoformat"):
            try:
                return value.isoformat()
            except TypeError:
                pass
        return value
