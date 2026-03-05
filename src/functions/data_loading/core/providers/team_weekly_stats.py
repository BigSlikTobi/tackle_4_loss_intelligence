"""Provider for team-level weekly stats from the games table."""

from __future__ import annotations

from typing import Any, Dict, List

from ...core.db.database_init import get_supabase_client

from .base import DataProvider


class _EmptyPipeline:
    def prepare(self, **_: Any) -> List[Dict[str, Any]]:
        return []


class TeamWeeklyStatsProvider(DataProvider):
    """Return team-week performance data using persisted game results."""

    def __init__(self) -> None:
        super().__init__(
            name="team_weekly_stats",
            pipeline=_EmptyPipeline(),  # unused, kept for interface compatibility
            fetch_keys=(),
        )
        self.client = get_supabase_client()
        if self.client is None:
            raise RuntimeError("Supabase client is not available")

    def get(self, *, output: str = "dict", **filters: Any) -> Any:  # type: ignore[override]
        season = filters.get("season")
        week = filters.get("week")
        team_abbr = str(filters.get("team_abbr", "")).strip().upper()

        if season is None:
            raise ValueError("team_weekly_stats provider requires a 'season' filter")
        if week is None:
            raise ValueError("team_weekly_stats provider requires a 'week' filter")
        if not team_abbr:
            raise ValueError("team_weekly_stats provider requires a 'team_abbr' filter")

        response = (
            self.client.table("games")
            .select("game_id,season,week,home_team,away_team,home_score,away_score,gameday,gametime,weekday")
            .eq("season", int(season))
            .eq("week", int(week))
            .or_(f"home_team.eq.{team_abbr},away_team.eq.{team_abbr}")
            .execute()
        )

        error = getattr(response, "error", None)
        if error:
            raise RuntimeError(f"Supabase error while fetching games: {error}")

        rows = getattr(response, "data", None) or []
        records = [self._to_team_week_record(team_abbr, row) for row in rows]
        return self._serialise(records, output)

    @staticmethod
    def _to_team_week_record(team_abbr: str, row: Dict[str, Any]) -> Dict[str, Any]:
        home_team = row.get("home_team")
        away_team = row.get("away_team")
        home_score = row.get("home_score")
        away_score = row.get("away_score")
        is_home = home_team == team_abbr

        points_for = home_score if is_home else away_score
        points_against = away_score if is_home else home_score

        result = None
        if points_for is not None and points_against is not None:
            if points_for > points_against:
                result = "W"
            elif points_for < points_against:
                result = "L"
            else:
                result = "T"

        return {
            "team_abbr": team_abbr,
            "season": row.get("season"),
            "week": row.get("week"),
            "game_id": row.get("game_id"),
            "opponent_team": away_team if is_home else home_team,
            "is_home": is_home,
            "points_for": points_for,
            "points_against": points_against,
            "point_diff": (
                (points_for - points_against)
                if points_for is not None and points_against is not None
                else None
            ),
            "result": result,
            "gameday": row.get("gameday"),
            "gametime": row.get("gametime"),
            "weekday": row.get("weekday"),
        }


__all__ = ["TeamWeeklyStatsProvider"]
