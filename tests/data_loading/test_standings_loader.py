"""Tests for StandingsDataLoader.load_data with a stubbed Supabase writer."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from src.functions.data_loading.core.data.loaders.standings import StandingsDataLoader
from src.functions.data_loading.core.pipelines import PipelineResult


class _StubWriter:
    def __init__(self) -> None:
        self.received: List[Dict[str, Any]] = []
        self.last_clear: bool = False

    def write(self, records: List[Dict[str, Any]], *, clear: bool = False) -> PipelineResult:
        self.received = list(records)
        self.last_clear = clear
        return PipelineResult(True, len(records), written=len(records))


class _StubSupabase:
    """Minimal stand-in for a Supabase client used by ``compute_standings_rows``."""

    def __init__(self, games: List[Dict[str, Any]], teams: List[Dict[str, Any]]) -> None:
        self._games = games
        self._teams = teams

    def table(self, name: str) -> "_StubTable":
        return _StubTable(self._games if name == "games" else self._teams)


class _StubTable:
    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self._rows = rows
        self._filters: Dict[str, Any] = {}

    def select(self, *_a, **_kw) -> "_StubTable":
        return self

    def eq(self, key: str, value: Any) -> "_StubTable":
        self._filters[key] = value
        return self

    def lte(self, key: str, value: Any) -> "_StubTable":
        self._filters[f"{key}__lte"] = value
        return self

    def order(self, *_a, **_kw) -> "_StubTable":
        return self

    def range(self, _start: int, _end: int) -> "_StubTable":
        return self

    def execute(self) -> "_Resp":
        rows = self._rows
        for key, value in self._filters.items():
            if key.endswith("__lte"):
                actual = key[:-5]
                rows = [r for r in rows if r.get(actual) is not None and r[actual] <= value]
            else:
                rows = [r for r in rows if r.get(key) == value]
        return _Resp(rows)


class _Resp:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data
        self.error = None


@pytest.fixture
def stub_data() -> Dict[str, List[Dict[str, Any]]]:
    teams = [
        {"team_abbr": "BUF", "team_name": "Bills", "team_conference": "AFC", "team_division": "AFC East"},
        {"team_abbr": "MIA", "team_name": "Dolphins", "team_conference": "AFC", "team_division": "AFC East"},
        {"team_abbr": "NE", "team_name": "Patriots", "team_conference": "AFC", "team_division": "AFC East"},
        {"team_abbr": "NYJ", "team_name": "Jets", "team_conference": "AFC", "team_division": "AFC East"},
    ]
    games = [
        {"game_id": "g1", "season": 2024, "week": 1, "game_type": "REG",
         "home_team": "BUF", "away_team": "MIA", "home_score": 24, "away_score": 17},
        {"game_id": "g2", "season": 2024, "week": 2, "game_type": "REG",
         "home_team": "BUF", "away_team": "NE", "home_score": 28, "away_score": 14},
    ]
    return {"games": games, "teams": teams}


def test_load_data_dry_run_does_not_write(stub_data):
    writer = _StubWriter()
    loader = StandingsDataLoader(
        writer=writer,
        supabase_client=_StubSupabase(stub_data["games"], stub_data["teams"]),
    )

    result = loader.load_data(season=2024, dry_run=True)
    assert result["success"] is True
    # NYJ never plays in the stub data, so they're filtered out as a
    # ghost / historical-alias row.
    assert result["records_processed"] == 3
    assert writer.received == []  # nothing written


def test_load_data_writes_rows(stub_data):
    writer = _StubWriter()
    loader = StandingsDataLoader(
        writer=writer,
        supabase_client=_StubSupabase(stub_data["games"], stub_data["teams"]),
    )

    result = loader.load_data(season=2024)
    assert result["success"] is True
    assert result["records_processed"] == 3
    assert result["records_written"] == 3
    assert len(writer.received) == 3
    assert {r["team_abbr"] for r in writer.received} == {"BUF", "MIA", "NE"}
    # BUF should be 2-0 and division_rank 1.
    buf = next(r for r in writer.received if r["team_abbr"] == "BUF")
    assert buf["wins"] == 2
    assert buf["division_rank"] == 1


def test_loader_clear_flag_is_ignored(stub_data):
    """``clear=True`` must NOT wipe historical snapshots."""
    writer = _StubWriter()
    loader = StandingsDataLoader(
        writer=writer,
        supabase_client=_StubSupabase(stub_data["games"], stub_data["teams"]),
    )
    loader.load_data(season=2024, clear=True)
    assert writer.last_clear is False


def test_through_week_filter(stub_data):
    writer = _StubWriter()
    loader = StandingsDataLoader(
        writer=writer,
        supabase_client=_StubSupabase(stub_data["games"], stub_data["teams"]),
    )
    loader.load_data(season=2024, through_week=1)
    buf = next(r for r in writer.received if r["team_abbr"] == "BUF")
    assert buf["wins"] == 1  # only week 1 counted
    assert buf["through_week"] == 1
