"""Tests for the per-team aggregation in core/standings/compute.py."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from src.functions.data_loading.core.standings.compute import (
    build_team_records,
    compute_standings_rows,
)


def _team(abbr: str, conference: str, division: str, name: str = None) -> Dict[str, Any]:
    return {
        "team_abbr": abbr,
        "team_name": name or abbr,
        "team_conference": conference,
        "team_division": division,
    }


def _game(
    week: int,
    home: str,
    away: str,
    home_score: int,
    away_score: int,
) -> Dict[str, Any]:
    return {
        "game_id": f"{week}-{home}-{away}",
        "season": 2024,
        "week": week,
        "game_type": "REG",
        "home_team": home,
        "away_team": away,
        "home_score": home_score,
        "away_score": away_score,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def afc_east_teams() -> List[Dict[str, Any]]:
    return [
        _team("BUF", "AFC", "AFC East"),
        _team("MIA", "AFC", "AFC East"),
        _team("NE", "AFC", "AFC East"),
        _team("NYJ", "AFC", "AFC East"),
    ]


@pytest.fixture
def four_div_league() -> List[Dict[str, Any]]:
    """A 16-team league spanning 2 conferences, 4 divisions, 4 teams each.

    Enough to exercise division ranking + conference seeding.
    """
    return [
        _team("BUF", "AFC", "AFC East"),
        _team("MIA", "AFC", "AFC East"),
        _team("NE", "AFC", "AFC East"),
        _team("NYJ", "AFC", "AFC East"),
        _team("BAL", "AFC", "AFC North"),
        _team("CIN", "AFC", "AFC North"),
        _team("CLE", "AFC", "AFC North"),
        _team("PIT", "AFC", "AFC North"),
        _team("DAL", "NFC", "NFC East"),
        _team("NYG", "NFC", "NFC East"),
        _team("PHI", "NFC", "NFC East"),
        _team("WAS", "NFC", "NFC East"),
        _team("CHI", "NFC", "NFC North"),
        _team("DET", "NFC", "NFC North"),
        _team("GB", "NFC", "NFC North"),
        _team("MIN", "NFC", "NFC North"),
    ]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def test_clean_records(afc_east_teams):
    games = [
        _game(1, "BUF", "MIA", 24, 17),
        _game(2, "BUF", "NE", 28, 14),
        _game(3, "BUF", "NYJ", 21, 20),
        _game(4, "MIA", "NE", 31, 10),
        _game(5, "MIA", "NYJ", 17, 14),
        _game(6, "NE", "NYJ", 13, 10),
    ]
    records = build_team_records(games=games, teams=afc_east_teams)

    buf = records["BUF"]
    assert buf.wins == 3 and buf.losses == 0 and buf.ties == 0
    assert buf.points_for == 24 + 28 + 21
    assert buf.points_against == 17 + 14 + 20
    assert buf.div_wins == 3
    assert buf.conf_wins == 3  # everyone in AFC East is also in AFC

    nyj = records["NYJ"]
    assert nyj.wins == 0 and nyj.losses == 3
    assert nyj.div_losses == 3

    assert records["MIA"].wins == 2
    assert records["NE"].wins == 1


def test_ties_count_as_half_win(afc_east_teams):
    games = [
        _game(1, "BUF", "MIA", 17, 17),
        _game(2, "NE", "NYJ", 21, 21),
    ]
    records = build_team_records(games=games, teams=afc_east_teams)
    for abbr in ("BUF", "MIA", "NE", "NYJ"):
        assert records[abbr].ties == 1
        assert records[abbr].wins == 0
        assert records[abbr].losses == 0
        assert records[abbr].win_pct == 0.5


def test_skips_incomplete_games(afc_east_teams):
    games = [
        _game(1, "BUF", "MIA", 24, 17),
        {**_game(2, "NE", "NYJ", 0, 0), "home_score": None, "away_score": None},
    ]
    records = build_team_records(games=games, teams=afc_east_teams)
    assert records["BUF"].wins == 1
    assert records["NE"].games_played == 0
    assert records["NYJ"].games_played == 0


def test_home_away_split(afc_east_teams):
    games = [
        _game(1, "BUF", "MIA", 24, 17),  # BUF home win
        _game(2, "NE", "BUF", 21, 30),  # BUF away win
        _game(3, "NYJ", "BUF", 28, 10),  # BUF away loss
    ]
    records = build_team_records(games=games, teams=afc_east_teams)
    buf = records["BUF"]
    assert buf.home_wins == 1 and buf.home_losses == 0
    assert buf.away_wins == 1 and buf.away_losses == 1


def test_streak_and_last5(afc_east_teams):
    games = [
        _game(1, "BUF", "MIA", 10, 24),  # BUF L
        _game(2, "BUF", "NE", 14, 7),   # BUF W
        _game(3, "BUF", "NYJ", 21, 20),  # BUF W
        _game(4, "MIA", "BUF", 17, 24),  # BUF W
    ]
    rows = compute_standings_rows(season=2024, games=games, teams=afc_east_teams, through_week=4)
    buf_row = next(r for r in rows if r["team_abbr"] == "BUF")
    assert buf_row["streak"] == "W3"
    # Only 4 games played → last5 should reflect 3W-1L.
    assert buf_row["last5"] == "3-1"


def test_compute_standings_rows_through_week(afc_east_teams):
    games = [
        _game(1, "BUF", "MIA", 24, 17),
        _game(2, "BUF", "NE", 28, 14),
        _game(3, "BUF", "NYJ", 21, 20),
        _game(4, "MIA", "NE", 31, 10),
    ]
    rows = compute_standings_rows(season=2024, games=games, teams=afc_east_teams, through_week=2)
    buf = next(r for r in rows if r["team_abbr"] == "BUF")
    assert buf["wins"] == 2
    assert buf["through_week"] == 2
    # NYJ is on the schedule (week 3) so they appear in the roster; they just
    # have no games played yet at the week-2 snapshot.
    nyj = next(r for r in rows if r["team_abbr"] == "NYJ")
    assert nyj["wins"] == 0 and nyj["losses"] == 0


def test_division_ranking_simple(afc_east_teams):
    """BUF goes 3-0, MIA 2-1, NE 1-2, NYJ 0-3 — ordering should follow win%."""
    games = [
        _game(1, "BUF", "MIA", 24, 17),
        _game(2, "BUF", "NE", 28, 14),
        _game(3, "BUF", "NYJ", 21, 20),
        _game(4, "MIA", "NE", 31, 10),
        _game(5, "MIA", "NYJ", 17, 14),
        _game(6, "NE", "NYJ", 13, 10),
    ]
    rows = compute_standings_rows(season=2024, games=games, teams=afc_east_teams, through_week=6)
    by_team = {r["team_abbr"]: r for r in rows}
    assert by_team["BUF"]["division_rank"] == 1
    assert by_team["MIA"]["division_rank"] == 2
    assert by_team["NE"]["division_rank"] == 3
    assert by_team["NYJ"]["division_rank"] == 4


def test_conference_seeding_with_winners(four_div_league):
    """Each AFC division winner takes a top-4 seed; sanity check ordering."""
    games = [
        # AFC East: BUF 2-0
        _game(1, "BUF", "MIA", 30, 10),
        _game(2, "BUF", "NE", 28, 14),
        # AFC North: BAL 2-0
        _game(1, "BAL", "CIN", 24, 17),
        _game(2, "BAL", "PIT", 21, 7),
        # NFC East: PHI 2-0
        _game(1, "PHI", "DAL", 28, 21),
        _game(2, "PHI", "NYG", 24, 14),
        # NFC North: DET 2-0
        _game(1, "DET", "GB", 31, 17),
        _game(2, "DET", "MIN", 28, 10),
    ]
    rows = compute_standings_rows(season=2024, games=games, teams=four_div_league, through_week=2)
    by_team = {r["team_abbr"]: r for r in rows}

    # AFC division winners.
    assert by_team["BUF"]["division_rank"] == 1
    assert by_team["BAL"]["division_rank"] == 1
    # Both are 2-0 division winners — they take seeds 1 and 2 in some order.
    afc_seeds = {by_team["BUF"]["conference_seed"], by_team["BAL"]["conference_seed"]}
    assert afc_seeds == {1, 2}

    # NFC division winners.
    assert by_team["PHI"]["division_rank"] == 1
    assert by_team["DET"]["division_rank"] == 1
    nfc_seeds = {by_team["PHI"]["conference_seed"], by_team["DET"]["conference_seed"]}
    assert nfc_seeds == {1, 2}


def test_historical_aliases_dropped_when_games_played():
    """Franchise aliases (e.g. STL/LA/LAR for the Rams) that didn't play in the
    requested season must not show up as 0-0-0 ghost rows in the standings."""
    teams = [
        _team("LA", "NFC", "NFC West"),
        _team("LAR", "NFC", "NFC West"),  # alias, no games this season
        _team("STL", "NFC", "NFC West"),  # alias, no games this season
        _team("SEA", "NFC", "NFC West"),
        _team("SF", "NFC", "NFC West"),
        _team("ARI", "NFC", "NFC West"),
    ]
    games = [
        _game(1, "LA", "SF", 21, 14),
        _game(2, "SEA", "ARI", 28, 10),
    ]
    rows = compute_standings_rows(season=2024, games=games, teams=teams, through_week=2)
    abbrs = {r["team_abbr"] for r in rows}
    assert "LAR" not in abbrs
    assert "STL" not in abbrs
    assert {"LA", "SEA", "SF", "ARI"} <= abbrs


def test_offseason_snapshot_keeps_all_teams(afc_east_teams):
    """When no games have been played, all teams should still appear (preseason)."""
    rows = compute_standings_rows(season=2024, games=[], teams=afc_east_teams, through_week=0)
    abbrs = {r["team_abbr"] for r in rows}
    assert abbrs == {"BUF", "MIA", "NE", "NYJ"}


def test_preseason_snapshot_with_schedule_loaded_drops_aliases():
    """`through_week=0` after the schedule lands: 32 active teams, all 0-0-0,
    historical aliases dropped because they're not on the new season's schedule."""
    teams = [
        _team("LA", "NFC", "NFC West"),
        _team("LAR", "NFC", "NFC West"),  # historical alias, not in schedule
        _team("STL", "NFC", "NFC West"),  # historical alias, not in schedule
        _team("SEA", "NFC", "NFC West"),
        _team("SF", "NFC", "NFC West"),
        _team("ARI", "NFC", "NFC West"),
    ]
    schedule = [
        # Future games — no scores yet, but the rostered set is determined
        # from the schedule, not from completed games.
        {**_game(1, "LA", "SEA", 0, 0), "home_score": None, "away_score": None},
        {**_game(2, "SF", "ARI", 0, 0), "home_score": None, "away_score": None},
    ]
    rows = compute_standings_rows(season=2026, games=schedule, teams=teams, through_week=0)
    abbrs = {r["team_abbr"] for r in rows}
    assert abbrs == {"LA", "SEA", "SF", "ARI"}
    for row in rows:
        assert row["wins"] == 0 and row["losses"] == 0 and row["ties"] == 0
        assert row["through_week"] == 0


def test_conference_and_league_rank_are_populated(four_div_league):
    """Every team has a conference_rank (1..N) and league_rank (1..N) set."""
    games = [
        _game(1, "BUF", "MIA", 30, 10),
        _game(2, "BUF", "NE", 28, 14),
        _game(3, "NYJ", "MIA", 17, 14),  # ensure NYJ on schedule
        _game(1, "BAL", "CIN", 24, 17),
        _game(2, "BAL", "PIT", 21, 7),
        _game(3, "CLE", "CIN", 10, 7),   # ensure CLE on schedule
        _game(1, "PHI", "DAL", 28, 21),
        _game(2, "PHI", "NYG", 24, 14),
        _game(3, "WAS", "DAL", 17, 14),  # ensure WAS on schedule
        _game(1, "DET", "GB", 31, 17),
        _game(2, "DET", "MIN", 28, 10),
        _game(3, "CHI", "GB", 14, 13),   # ensure CHI on schedule
    ]
    rows = compute_standings_rows(season=2024, games=games, teams=four_div_league, through_week=3)

    afc_ranks = sorted(r["conference_rank"] for r in rows if r["conference"] == "AFC")
    nfc_ranks = sorted(r["conference_rank"] for r in rows if r["conference"] == "NFC")
    # 8 teams per conference, ranks must be 1..8 with no holes.
    assert afc_ranks == list(range(1, 9))
    assert nfc_ranks == list(range(1, 9))

    league_ranks = sorted(r["league_rank"] for r in rows)
    assert league_ranks == list(range(1, 17))

    # Top conference rank teams (4 division winners) take seeds 1-4 of their
    # conference. With everyone 2-0, conference_rank 1..4 maps to seeds 1..4.
    for row in rows:
        if row["conference_rank"] is not None and row["conference_rank"] <= 7:
            assert row["conference_seed"] == row["conference_rank"]
        else:
            assert row["conference_seed"] is None


def test_emitted_row_shape_matches_table_schema(afc_east_teams):
    """Sanity: the dict keys produced by compute_standings_rows match the standings table columns."""
    games = [_game(1, "BUF", "MIA", 24, 17)]
    rows = compute_standings_rows(season=2024, games=games, teams=afc_east_teams, through_week=1)
    expected = {
        "season",
        "through_week",
        "team_abbr",
        "team_name",
        "conference",
        "division",
        "wins",
        "losses",
        "ties",
        "win_pct",
        "points_for",
        "points_against",
        "point_diff",
        "division_record",
        "conference_record",
        "home_record",
        "away_record",
        "last5",
        "streak",
        "division_rank",
        "conference_rank",
        "conference_seed",
        "league_rank",
        "clinched",
        "tiebreaker_trail",
        "tied",
    }
    assert set(rows[0].keys()) == expected
