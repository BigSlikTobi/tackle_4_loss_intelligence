"""CLI for loading and viewing NFL game schedules.

Two modes:

* Default: fetch the schedule from nflreadpy and upsert into the
  ``games`` table on conflict of ``game_id``. Auto-detects the latest
  season from the source when ``--season`` is omitted.
* ``--show [VALUE]``: print stored games (read-only). The argument can be:
    - omitted        → the current week's slate (auto-detected)
    - a week number  → that week's slate (e.g. ``--show 5``)
    - a team abbr    → all of that team's games this season (e.g. ``--show NYJ``)
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.shared.utils.env import load_env  # noqa: E402
from src.functions.data_loading.core.utils.cli import (  # noqa: E402
    setup_cli_parser,
    setup_cli_logging,
    print_results,
    maybe_show_columns,
    handle_cli_errors,
)
from src.functions.data_loading.core.utils.season import (  # noqa: E402
    get_current_season,
    get_current_week_and_season_type,
)
from src.functions.data_loading.core.data.loaders.game import GamesDataLoader  # noqa: E402


def _resolve_display_season(client, requested: Optional[int]) -> Optional[int]:
    """Pick the season to display when the user didn't pass --season.

    Calendar default (``get_current_season()``) can sit ahead of the data —
    e.g. in April–May before the next-year schedule is published. Try the
    calendar default first; if the games table has zero rows for it, fall
    back to ``max(season)`` actually present.
    """
    if requested is not None:
        return requested

    calendar_default = get_current_season()
    probe = (
        client.table("games")
        .select("game_id")
        .eq("season", calendar_default)
        .limit(1)
        .execute()
    )
    if getattr(probe, "data", None):
        return calendar_default

    fallback = (
        client.table("games")
        .select("season")
        .order("season", desc=True)
        .limit(1)
        .execute()
    )
    rows = getattr(fallback, "data", None) or []
    if rows and rows[0].get("season") is not None:
        latest = int(rows[0]["season"])
        print(
            f"(season {calendar_default} has no games yet; falling back to {latest})",
            file=sys.stderr,
        )
        return latest
    return calendar_default


def _format_game_line(row: Dict[str, Any]) -> str:
    """One-line representation of a game: 'Sun 4:25 PM  NYJ @ NE  21-17 (F)' or scheduled form."""
    weekday = (row.get("weekday") or "").strip()[:3]
    gameday = (row.get("gameday") or "").strip()
    gametime = (row.get("gametime") or "").strip()
    away = (row.get("away_team") or "?").strip().upper()
    home = (row.get("home_team") or "?").strip().upper()
    away_score = row.get("away_score")
    home_score = row.get("home_score")

    when = " ".join(filter(None, [weekday, gameday, gametime])).strip()
    matchup = f"{away:>3} @ {home:<3}"

    if away_score is not None and home_score is not None:
        try:
            a = int(float(away_score))
            h = int(float(home_score))
            return f"  {when:<24}  {matchup}  {a:>2}-{h:<2}"
        except (TypeError, ValueError):
            pass
    return f"  {when:<24}  {matchup}  (scheduled)"


def _show_week(week: int, season: Optional[int]) -> bool:
    from src.shared.db.connection import get_supabase_client

    client = get_supabase_client()
    season = _resolve_display_season(client, season)
    response = (
        client.table("games")
        .select(
            "game_id, season, week, weekday, gameday, gametime, "
            "away_team, away_score, home_team, home_score"
        )
        .eq("season", season)
        .eq("week", week)
        .order("gameday")
        .order("gametime")
        .execute()
    )
    rows: List[Dict[str, Any]] = getattr(response, "data", None) or []
    if not rows:
        print(f"No games found for {season} Week {week}.")
        return True

    completed = [r for r in rows if r.get("home_score") is not None]
    print(f"{season} Week {week} — {len(rows)} game(s), {len(completed)} completed:")
    for row in rows:
        print(_format_game_line(row))
    return True


def _show_team(team: str, season: Optional[int]) -> bool:
    from src.shared.db.connection import get_supabase_client

    client = get_supabase_client()
    season = _resolve_display_season(client, season)
    team_upper = team.upper()
    response = (
        client.table("games")
        .select(
            "game_id, season, week, weekday, gameday, gametime, "
            "away_team, away_score, home_team, home_score"
        )
        .eq("season", season)
        .or_(f"home_team.eq.{team_upper},away_team.eq.{team_upper}")
        .order("week")
        .execute()
    )
    rows: List[Dict[str, Any]] = getattr(response, "data", None) or []
    if not rows:
        print(f"No games found for {team_upper} in season {season}.")
        return True

    wins = losses = ties = 0
    for r in rows:
        a = r.get("away_score")
        h = r.get("home_score")
        if a is None or h is None:
            continue
        try:
            a, h = float(a), float(h)
        except (TypeError, ValueError):
            continue
        if r.get("home_team", "").upper() == team_upper:
            mine, theirs = h, a
        else:
            mine, theirs = a, h
        if mine > theirs:
            wins += 1
        elif mine < theirs:
            losses += 1
        else:
            ties += 1

    record = f"{wins}-{losses}" + (f"-{ties}" if ties else "")
    print(f"{team_upper} — {season} season ({len(rows)} games, record {record}):")
    for row in rows:
        prefix = f"W{row.get('week'):>2}"
        line = _format_game_line(row)
        print(f"  {prefix}{line[2:]}")  # replace leading "  " from _format_game_line
    return True


def _print_load_rollup(season: int) -> None:
    from src.shared.db.connection import get_supabase_client

    client = get_supabase_client()
    response = (
        client.table("games")
        .select("season, weekday, away_score, home_score")
        .eq("season", season)
        .execute()
    )
    rows: List[Dict[str, Any]] = getattr(response, "data", None) or []
    if not rows:
        return

    completed = [r for r in rows if r.get("home_score") is not None]
    scheduled = len(rows) - len(completed)
    by_weekday = Counter((r.get("weekday") or "?").strip()[:3] or "?" for r in rows)

    print(f"\nGames table now holds {len(rows)} record(s) for season {season}:")
    print(f"  completed:  {len(completed):>3}")
    print(f"  scheduled:  {scheduled:>3}")
    if by_weekday:
        cells = ", ".join(f"{day}={count}" for day, count in sorted(by_weekday.items()))
        print(f"  by weekday: {cells}")


@handle_cli_errors
def main() -> None:
    parser: argparse.ArgumentParser = setup_cli_parser(
        description="Load NFL game schedules into the database, or view stored games with --show.",
    )
    parser.add_argument(
        "--season",
        type=int,
        help="Season year to load or display. Defaults to the latest available season.",
    )
    parser.add_argument(
        "--week",
        type=int,
        help="Specific week to load (1–18). Omit to load the entire season.",
    )
    parser.add_argument(
        "--show",
        nargs="?",
        const="__current__",
        default=None,
        metavar="TEAM_OR_WEEK",
        help=(
            "View stored games (read-only). With no value: current week's slate. "
            "With a number: that week's slate. With a team abbr (e.g. NYJ): that "
            "team's full season."
        ),
    )
    args = parser.parse_args()
    setup_cli_logging(args)
    load_env()

    if args.show is not None:
        value = args.show.strip()
        if value == "__current__":
            current_week, _ = get_current_week_and_season_type()
            if current_week is None:
                print(
                    "Outside the NFL calendar window. Pass an explicit week "
                    "(e.g. --show 5) or a team abbr (e.g. --show NYJ).",
                    file=sys.stderr,
                )
                return True
            return _show_week(current_week, args.season)
        if value.isdigit():
            return _show_week(int(value), args.season)
        return _show_team(value, args.season)

    loader = GamesDataLoader()
    fetch_params = {"season": args.season, "week": args.week}
    if maybe_show_columns(loader, args, **fetch_params):
        return True

    result = loader.load_data(dry_run=args.dry_run, clear=args.clear, **fetch_params)
    print_results(result, operation="games load", dry_run=args.dry_run)

    if not args.dry_run and getattr(result, "success", True):
        try:
            from src.shared.db.connection import get_supabase_client
            target_season = _resolve_display_season(
                get_supabase_client(), args.season
            )
            _print_load_rollup(target_season)
        except Exception as exc:  # pragma: no cover - summary is best-effort
            print(f"(skipped post-load summary: {exc})")
    return True


if __name__ == "__main__":
    main()
