"""Provider for team-level season aggregates from the games table."""

from __future__ import annotations

from typing import Any, Dict, List

from ...core.db.database_init import get_supabase_client
from .base import DataProvider


class _EmptyPipeline:
    def prepare(self, **_: Any) -> List[Dict[str, Any]]:
        return []


class TeamSeasonStatsProvider(DataProvider):
    """Return season aggregates for a team using persisted game results."""

    def __init__(self) -> None:
        super().__init__(
            name="team_season_stats",
            pipeline=_EmptyPipeline(),
            fetch_keys=(),
        )
        self.client = get_supabase_client()
        if self.client is None:
            raise RuntimeError("Supabase client is not available")

    def get(self, *, output: str = "dict", **filters: Any) -> Any:  # type: ignore[override]
        season = filters.get("season")
        team_abbr = str(filters.get("team_abbr", "")).strip().upper()

        if season is None:
            raise ValueError("team_season_stats provider requires a 'season' filter")
        if not team_abbr:
            raise ValueError("team_season_stats provider requires a 'team_abbr' filter")

        response = (
            self.client.table("games")
            .select("game_id,season,week,home_team,away_team,home_score,away_score")
            .eq("season", int(season))
            .or_(f"home_team.eq.{team_abbr},away_team.eq.{team_abbr}")
            .execute()
        )
        error = getattr(response, "error", None)
        if error:
            raise RuntimeError(f"Supabase error while fetching season games: {error}")

        games = getattr(response, "data", None) or []
        summary = self._build_summary(team_abbr=team_abbr, season=int(season), games=games)
        return self._serialise([summary], output)

    @staticmethod
    def _build_summary(*, team_abbr: str, season: int, games: List[Dict[str, Any]]) -> Dict[str, Any]:
        wins = losses = ties = 0
        points_for = points_against = 0
        played = 0

        for game in games:
            home_team = game.get("home_team")
            away_team = game.get("away_team")
            home_score = game.get("home_score")
            away_score = game.get("away_score")

            if home_score is None or away_score is None:
                continue

            is_home = home_team == team_abbr
            pf = int(home_score) if is_home else int(away_score)
            pa = int(away_score) if is_home else int(home_score)

            played += 1
            points_for += pf
            points_against += pa

            if pf > pa:
                wins += 1
            elif pf < pa:
                losses += 1
            else:
                ties += 1

        return {
            "team_abbr": team_abbr,
            "season": season,
            "games_played": played,
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "record": f"{wins}-{losses}-{ties}",
            "points_for": points_for,
            "points_against": points_against,
            "point_diff": points_for - points_against,
            "points_for_per_game": (points_for / played) if played else None,
            "points_against_per_game": (points_against / played) if played else None,
        }


__all__ = ["TeamSeasonStatsProvider"]
