"""CLI for loading NFL player metadata.

Two modes:

* Default: fetch player metadata from nflreadpy and upsert into the
  ``players`` table on conflict of ``player_id``.
* ``--show TEAM``: print the players whose ``latest_team`` is TEAM,
  grouped by position (read-only).

Filtering:
    Without filters, ALL historical players (~25k+ rows) are loaded.
    For most use cases (current rosters, ETL pipelines), pass
    ``--active-only`` which restricts to players whose ``status`` is
    Active AND whose ``last_season`` is the previous year or later.

    ``--clear`` wipes the entire ``players`` table before insert. Use
    with care — there is no transaction wrapper, so a failed insert
    after a successful clear will leave the table empty.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.shared.utils.env import load_env  # noqa: E402
from src.functions.data_loading.core.utils.cli import (  # noqa: E402
    setup_cli_parser,
    setup_cli_logging,
    print_results,
    maybe_show_columns,
    handle_cli_errors,
)
from src.functions.data_loading.core.data.loaders.player import (  # noqa: E402
    PlayersDataLoader,
)


def _show_players_for_team(team: str) -> bool:
    """Print players whose latest_team is TEAM, grouped by position."""
    from src.shared.db.connection import get_supabase_client

    team_upper = team.upper()
    client = get_supabase_client()
    response = (
        client.table("players")
        .select("player_id, display_name, position, status, last_season")
        .eq("latest_team", team_upper)
        .execute()
    )
    rows: List[Dict[str, Any]] = getattr(response, "data", None) or []
    if not rows:
        print(f"No players found with latest_team = {team_upper}.")
        return True

    by_position: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        pos = (row.get("position") or "OTHER").upper()
        by_position[pos].append(row)

    active_count = sum(
        1 for r in rows if (r.get("status") or "").lower().startswith("act")
    )
    print(
        f"{team_upper} — {len(rows)} player(s) tagged as latest_team "
        f"({active_count} active):"
    )
    for pos in sorted(by_position):
        entries = sorted(
            by_position[pos],
            key=lambda r: (r.get("display_name") or ""),
        )
        names = []
        for entry in entries:
            name = entry.get("display_name") or entry.get("player_id") or "?"
            status = (entry.get("status") or "").strip()
            last = entry.get("last_season")
            tag = ""
            if status and not status.lower().startswith("act"):
                tag = f" [{status}]"
            elif last is not None:
                tag = f" ({last})"
            names.append(f"{name}{tag}")
        print(f"  {pos:<6} ({len(names):>2})  " + ", ".join(names))
    return True


def _print_player_rollup() -> None:
    """Read the players table and print a position/team summary."""
    from src.shared.db.connection import get_supabase_client

    client = get_supabase_client()
    rows: List[Dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            client.table("players")
            .select("position, latest_team, status")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        data = getattr(resp, "data", None) or []
        if not data:
            break
        rows.extend(data)
        if len(data) < page_size:
            break
        offset += page_size

    if not rows:
        print("(players table is empty after load)")
        return

    pos_counts = Counter(
        (r.get("position") or "?").upper() for r in rows if r.get("position")
    )
    team_counts = Counter(
        (r.get("latest_team") or "?").upper() for r in rows if r.get("latest_team")
    )
    active_count = sum(
        1 for r in rows if (r.get("status") or "").lower().startswith("act")
    )

    print(
        f"\nPlayers table now holds {len(rows):,} records "
        f"({active_count:,} active)."
    )
    if pos_counts:
        top = pos_counts.most_common(10)
        cells = "  ".join(f"{pos}={count}" for pos, count in top)
        print(f"  by position (top 10):  {cells}")
    if team_counts:
        if team_counts:
            avg = len(rows) / max(len(team_counts), 1)
            min_team, min_count = min(team_counts.items(), key=lambda x: x[1])
            max_team, max_count = max(team_counts.items(), key=lambda x: x[1])
            print(
                f"  by team:               {len(team_counts)} teams "
                f"(avg {avg:.0f} each, min {min_team}={min_count}, max {max_team}={max_count})"
            )


@handle_cli_errors
def main() -> None:
    parser: argparse.ArgumentParser = setup_cli_parser(
        description="Load NFL player metadata into the database.",
    )
    parser.add_argument(
        "--active-only",
        action="store_true",
        help=(
            "Restrict to players with status=Active. Implicitly sets "
            "--min-last-season to (current year - 1) unless overridden."
        ),
    )
    parser.add_argument(
        "--min-last-season",
        type=int,
        dest="min_last_season",
        help=(
            "Keep only players whose last_season >= this value. "
            "Auto-defaults to (current year - 1) when --active-only is set."
        ),
    )
    parser.add_argument(
        "--show",
        type=str,
        metavar="TEAM",
        help=(
            "Print players whose latest_team is TEAM, grouped by position "
            "(read-only). Bypasses fetching and writing."
        ),
    )
    args = parser.parse_args()
    setup_cli_logging(args)
    load_env()

    if args.show:
        return _show_players_for_team(args.show)

    if not args.active_only and args.min_last_season is None:
        print(
            "WARNING: no filters provided. Loading ALL historical players "
            "(~25k+ rows). Pass --active-only for current rosters, or "
            "--min-last-season YYYY to bound the load.\n",
            file=sys.stderr,
        )

    loader = PlayersDataLoader()
    fetch_params = {
        "active_only": args.active_only,
        "min_last_season": args.min_last_season,
    }
    if maybe_show_columns(loader, args, **fetch_params):
        return True

    result = loader.load_data(
        dry_run=args.dry_run,
        clear=args.clear,
        **fetch_params,
    )
    print_results(result, operation="players load", dry_run=args.dry_run)

    if not args.dry_run and getattr(result, "success", True):
        try:
            _print_player_rollup()
        except Exception as exc:  # pragma: no cover - summary is best-effort
            print(f"(skipped post-load summary: {exc})")
    return True


if __name__ == "__main__":
    main()
