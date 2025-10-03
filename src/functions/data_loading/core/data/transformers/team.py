"""Transformers for team-related datasets."""

from __future__ import annotations

from typing import Any, Dict

from ....core.data.transform import BaseDataTransformer


class TeamDataTransformer(BaseDataTransformer):
    """Transform team metadata into Supabase-ready records."""

    required_fields = ["team_abbr"]

    def sanitize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        abbr = record.get("team_abbr") or record.get("abbr") or record.get("team")
        location = record.get("team_location") or record.get("location")
        nickname = record.get("team_nick") or record.get("team_nickname") or record.get("nickname")
        name = (
            record.get("team_name")
            or record.get("full_name")
            or (f"{location} {nickname}".strip() if location or nickname else None)
            or record.get("name")
        )
        abbr = abbr.upper() if isinstance(abbr, str) else abbr
        conference = (record.get("team_conference") or record.get("conference"))
        division = (record.get("team_division") or record.get("division"))
        nick = nickname
        updated_at = record.get("updated_at") or record.get("last_modified_date")
        if updated_at is None:
            from datetime import datetime, timezone

            updated_at = datetime.now(timezone.utc).isoformat()

        return {
            "team_abbr": abbr,
            "team_name": name,
            "team_conference": conference,
            "team_division": division,
            "team_nick": nick,
            "updated_at": updated_at,
        }
