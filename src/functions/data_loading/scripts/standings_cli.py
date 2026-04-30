"""CLI for computing NFL standings and persisting them to the ``standings`` table.

Two modes:

* Default: compute season-to-date standings from the ``games`` + ``teams``
  tables and upsert into ``standings`` (one row per team, keyed on
  ``(season, through_week, team_abbr)``).
* ``--show``: read-only display of the persisted standings, optionally
  filtered by division or conference.

Examples::

    python scripts/standings_cli.py                                  # current season, latest completed week
    python scripts/standings_cli.py --season 2024 --through-week 18  # final 2024 standings
    python scripts/standings_cli.py --dry-run                        # compute + print, no write
    python scripts/standings_cli.py --show --conference AFC          # read-back AFC seeds
    python scripts/standings_cli.py --show --division "AFC East"     # read-back one division
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.shared.utils.env import load_env  # noqa: E402
from src.functions.data_loading.core.data.loaders.standings import (  # noqa: E402
    StandingsDataLoader,
)
from src.functions.data_loading.core.utils.cli import (  # noqa: E402
    handle_cli_errors,
    print_results,
    setup_cli_logging,
    setup_cli_parser,
)
from src.functions.data_loading.core.utils.season import get_current_season  # noqa: E402


def _resolve_season(client: Any, requested: Optional[int]) -> int:
    """Pick a season for read-back. Falls back to ``max(season)`` in standings."""
    if requested is not None:
        return requested
    calendar_default = get_current_season()
    probe = (
        client.table("standings")
        .select("season")
        .eq("season", calendar_default)
        .limit(1)
        .execute()
    )
    if getattr(probe, "data", None):
        return calendar_default
    fallback = (
        client.table("standings")
        .select("season")
        .order("season", desc=True)
        .limit(1)
        .execute()
    )
    rows = getattr(fallback, "data", None) or []
    if rows and rows[0].get("season") is not None:
        latest = int(rows[0]["season"])
        if latest != calendar_default:
            print(
                f"(season {calendar_default} has no standings yet; falling back to {latest})",
                file=sys.stderr,
            )
        return latest
    return calendar_default


def _resolve_through_week(client: Any, season: int, requested: Optional[int]) -> int:
    """Pick the latest available through_week snapshot for read-back."""
    if requested is not None:
        return requested
    response = (
        client.table("standings")
        .select("through_week")
        .eq("season", season)
        .order("through_week", desc=True)
        .limit(1)
        .execute()
    )
    rows = getattr(response, "data", None) or []
    if rows and rows[0].get("through_week") is not None:
        return int(rows[0]["through_week"])
    return 0


def _show(args: argparse.Namespace) -> bool:
    from src.shared.db.connection import get_supabase_client

    client = get_supabase_client()
    if client is None:
        print("Supabase client unavailable", file=sys.stderr)
        return False

    season = _resolve_season(client, args.season)
    through_week = _resolve_through_week(client, season, args.through_week)

    query = (
        client.table("standings")
        .select("*")
        .eq("season", season)
        .eq("through_week", through_week)
    )
    if args.conference:
        query = query.eq("conference", args.conference.upper())
    if args.division:
        query = query.eq("division", args.division)

    response = query.execute()
    rows: List[Dict[str, Any]] = getattr(response, "data", None) or []
    if not rows:
        print(
            f"No standings rows for season={season}, through_week={through_week}"
            + (f", conference={args.conference}" if args.conference else "")
            + (f", division={args.division}" if args.division else "")
        )
        return True

    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return True

    if args.conference:
        rows.sort(
            key=lambda r: (
                r.get("conference_seed") if r.get("conference_seed") is not None else 99,
                -(r.get("win_pct") or 0),
                -(r.get("point_diff") or 0),
            )
        )
    elif args.division:
        rows.sort(key=lambda r: r.get("division_rank") or 99)
    else:
        rows.sort(
            key=lambda r: (
                r.get("conference") or "",
                r.get("division") or "",
                r.get("division_rank") or 99,
            )
        )

    _print_table(rows, season=season, through_week=through_week)
    return True


def _print_table(rows: List[Dict[str, Any]], *, season: int, through_week: int) -> None:
    print(f"Standings — season {season}, through week {through_week}")
    print()
    header = (
        f"{'#':>2}  {'Team':<5} {'W':>2} {'L':>2} {'T':>2}  {'Pct':>5}  "
        f"{'PF':>4} {'PA':>4} {'Diff':>5}  {'Div':<7} {'Conf':<7}  "
        f"{'Streak':<6} {'Last5':<6}  {'Seed':>4}  Trail"
    )
    print(header)
    print("-" * len(header))
    last_section = None
    for row in rows:
        section = (row.get("conference"), row.get("division"))
        if section != last_section and last_section is not None:
            print()
        last_section = section
        rank = row.get("conference_seed") or row.get("division_rank") or "-"
        seed = row.get("conference_seed")
        trail = ",".join(row.get("tiebreaker_trail") or [])
        print(
            f"{rank!s:>2}  {row.get('team_abbr',''):<5} "
            f"{row.get('wins',0):>2} {row.get('losses',0):>2} {row.get('ties',0):>2}  "
            f"{row.get('win_pct',0):>5.3f}  "
            f"{row.get('points_for',0):>4} {row.get('points_against',0):>4} {row.get('point_diff',0):>+5}  "
            f"{row.get('division_record',''):<7} {row.get('conference_record',''):<7}  "
            f"{row.get('streak',''):<6} {row.get('last5',''):<6}  "
            f"{(str(seed) if seed else '-'):>4}  {trail}"
        )


def _print_dry_run(rows: List[Dict[str, Any]]) -> None:
    rows = sorted(
        rows,
        key=lambda r: (
            r.get("conference") or "",
            r.get("division") or "",
            r.get("division_rank") or 99,
        ),
    )
    if not rows:
        print("(no rows computed)")
        return
    season = rows[0].get("season")
    through_week = rows[0].get("through_week")
    _print_table(rows, season=season, through_week=through_week)


@handle_cli_errors
def main() -> bool:
    parser: argparse.ArgumentParser = setup_cli_parser(
        description=(
            "Compute and persist NFL standings (default), "
            "or read back persisted standings with --show."
        ),
    )
    parser.add_argument("--season", type=int, help="Season year (default: current).")
    parser.add_argument(
        "--through-week",
        type=int,
        help=(
            "Snapshot point (1-18). Default: max completed REG week. "
            "Use 0 for an empty pre-Week-1 snapshot."
        ),
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Read-only: display persisted standings instead of recomputing.",
    )
    parser.add_argument(
        "--conference",
        help="Filter (with --show) to a conference: AFC or NFC.",
    )
    parser.add_argument(
        "--division",
        help='Filter (with --show) to a division, e.g. "AFC East".',
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit raw JSON (with --show or --dry-run).",
    )
    args = parser.parse_args()
    setup_cli_logging(args)
    load_env()

    if args.show:
        return _show(args)

    season = args.season if args.season is not None else get_current_season()
    loader = StandingsDataLoader()

    if args.dry_run or args.json:
        rows = loader.prepare(season=season, through_week=args.through_week)
        if args.json:
            print(json.dumps(rows, indent=2, default=str))
            return True
        _print_dry_run(rows)
        print(f"\nDRY RUN — would upsert {len(rows)} standings rows.")
        return True

    result = loader.load_data(season=season, through_week=args.through_week)
    print_results(result, operation="standings load", dry_run=False)
    return bool(result.get("success", True))


if __name__ == "__main__":
    sys.exit(main())
