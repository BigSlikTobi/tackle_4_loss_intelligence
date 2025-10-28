"""Team metadata retrieval helpers for the daily team update pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from ..integration.supabase_client import SupabaseClient


@dataclass(slots=True)
class TeamRecord:
    """Lightweight representation of a team row from Supabase."""

    identifier: Optional[str]
    abbreviation: str
    name: Optional[str]
    conference: Optional[str]
    division: Optional[str]
    metadata: Dict[str, object]


class TeamReader:
    """Fetches team metadata from Supabase and normalises fields."""

    def __init__(self, client: SupabaseClient) -> None:
        self._client = client

    def fetch_all(self, abbreviations: Optional[Sequence[str]] = None) -> List[TeamRecord]:
        """Return all teams filtered by optional abbreviations."""

        raw = self._client.fetch_teams()
        lookup = {abbr.upper() for abbr in abbreviations} if abbreviations else None
        records: List[TeamRecord] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            abbr = (row.get("abbr") or row.get("team_abbr") or row.get("slug") or "").upper()
            if not abbr:
                continue
            if lookup and abbr not in lookup:
                continue
            record = TeamRecord(
                identifier=row.get("id") or row.get("uuid"),
                abbreviation=abbr,
                name=row.get("name") or row.get("display_name"),
                conference=row.get("conference"),
                division=row.get("division"),
                metadata=row,
            )
            records.append(record)
        return records

    def fetch_single(self, abbreviation: str) -> Optional[TeamRecord]:
        """Return a single team record by abbreviation."""

        results = self.fetch_all([abbreviation])
        return results[0] if results else None
