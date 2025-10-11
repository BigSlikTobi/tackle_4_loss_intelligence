"""Transform scraped NFL injury reports into database-ready records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd  # type: ignore

from ....core.data.team_abbr import normalize_team_abbr
from ....core.data.transform import BaseDataTransformer


_TEAM_NAME_TO_ABBR: Dict[str, str] = {
    "arizonacardinals": "ARI",
    "atlantafalcons": "ATL",
    "baltimoreravens": "BAL",
    "buffalobills": "BUF",
    "carolinapanthers": "CAR",
    "chicagobears": "CHI",
    "cincinnatibengals": "CIN",
    "clevelandbrowns": "CLE",
    "dallascowboys": "DAL",
    "denverbroncos": "DEN",
    "detroitlions": "DET",
    "greenbaypackers": "GB",
    "houstontexans": "HOU",
    "indianapoliscolts": "IND",
    "jacksonvillejaguars": "JAX",
    "kansascitychiefs": "KC",
    "lasvegasraiders": "LV",
    "oaklandraiders": "LV",
    "losangeleschargers": "LAC",
    "sandiegochargers": "LAC",
    "losangelesrams": "LA",
    "stlouisrams": "LA",
    "larams": "LA",
    "miamidolphins": "MIA",
    "minnesotavikings": "MIN",
    "newenglandpatriots": "NE",
    "neworleanssaints": "NO",
    "newyorkgiants": "NYG",
    "newyorkjets": "NYJ",
    "philadelphiaeagles": "PHI",
    "pittsburghsteelers": "PIT",
    "sanfrancisco49ers": "SF",
    "seattleseahawks": "SEA",
    "tampabaybuccaneers": "TB",
    "tennesseetitans": "TEN",
    "washingtoncommanders": "WAS",
    "washingtonfootballteam": "WAS",
}


class InjuryDataTransformer(BaseDataTransformer):
    """Clean raw injury rows scraped from nfl.com."""

    required_fields = ["team_abbr", "player_name"]

    def sanitize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        team_abbr = _clean_str(record.get("team_abbr"))
        team_name = _clean_str(record.get("team_name"))
        resolved_team = normalize_team_abbr(team_abbr) if team_abbr else None
        if not resolved_team and team_name:
            resolved_team = _TEAM_NAME_TO_ABBR.get(_normalise_team_name(team_name))

        player_name = _clean_str(record.get("player_name"))
        injury = _clean_str(record.get("injury"))
        practice_status = _format_status(record.get("practice_status"))
        game_status = _format_status(record.get("game_status"))

        source_player_id = _clean_str(
            record.get("source_player_id") or record.get("player_id")
        )
        player_id = _clean_str(record.get("player_id") or source_player_id)

        last_update = _coerce_timestamp(record.get("last_update"))
        if last_update is None:
            last_update = datetime.now(timezone.utc).isoformat()

        return {
            "team_abbr": resolved_team,
            "player_name": player_name,
            "injury": injury,
            "practice_status": practice_status,
            "game_status": game_status,
            "source_player_id": source_player_id,
            "player_id": player_id,
            "last_update": last_update,
        }


def _clean_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"--", "-"}:
        return None
    return " ".join(text.split())


def _normalise_team_name(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


_STATUS_ALIASES: Dict[str, str] = {
    "dnp": "Did Not Practice",
    "didnotpractice": "Did Not Practice",
    "lp": "Limited",
    "limitedpractice": "Limited",
    "fp": "Full",
    "fullpractice": "Full",
    "questionable": "Questionable",
    "doubtful": "Doubtful",
    "out": "Out",
    "ir": "IR",
}


def _format_status(value: Any) -> Optional[str]:
    text = _clean_str(value)
    if text is None:
        return None
    key = text.lower().replace(" ", "")
    if key in _STATUS_ALIASES:
        return _STATUS_ALIASES[key]
    return " ".join(word.capitalize() for word in text.split())


def _coerce_timestamp(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = pd.to_datetime(value, utc=True).to_pydatetime()
        except Exception:  # pragma: no cover - defensive
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()
