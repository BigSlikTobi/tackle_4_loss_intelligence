"""CLI for loading and viewing NFL team rosters.

Two modes:

* Default: fetch the latest weekly roster snapshot from nflreadpy and
  persist a versioned record. Each run creates a new version per
  (season, week); previous versions are flagged ``is_current=false``.

* ``--show TEAM``: print the most recent stored roster for a single
  team, grouped by position. Read-only.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
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
    RostersDataLoader,
)


# Coarse position groups for `--show`. Anything not in this map falls under "OTHER".
_POSITION_GROUPS: List[tuple] = [
    ("QB",  {"QB"}),
    ("RB",  {"RB", "FB", "HB"}),
    ("WR",  {"WR"}),
    ("TE",  {"TE"}),
    ("OL",  {"OL", "C", "G", "T", "LT", "LG", "RG", "RT", "OT", "OG"}),
    ("DL",  {"DL", "DT", "DE", "NT", "EDGE"}),
    ("LB",  {"LB", "ILB", "OLB", "MLB"}),
    ("DB",  {"DB", "CB", "S", "FS", "SS", "NB"}),
    ("ST",  {"K", "P", "LS", "KR", "PR"}),
]


def _show_roster(team: str) -> bool:
    """Print the most recent stored roster for `team` and return True."""

    from src.shared.db.connection import get_supabase_client

    team_upper = team.upper()
    client = get_supabase_client()

    response = (
        client.table("rosters")
        .select("team, season, week, version, depth_chart_position, player")
        .eq("team", team_upper)
        .eq("is_current", True)
        .execute()
    )
    rows: List[Dict[str, Any]] = getattr(response, "data", None) or []

    if not rows:
        print(f"No current roster found for team {team_upper}.")
        return True

    player_ids = sorted({r["player"] for r in rows if r.get("player")})
    name_by_id: Dict[str, str] = {}
    for i in range(0, len(player_ids), 200):
        chunk = player_ids[i : i + 200]
        resp = (
            client.table("players")
            .select("player_id, display_name, first_name, last_name")
            .in_("player_id", chunk)
            .execute()
        )
        for p in getattr(resp, "data", None) or []:
            display = p.get("display_name")
            if not display:
                first = (p.get("first_name") or "").strip()
                last = (p.get("last_name") or "").strip()
                display = f"{first[:1]}. {last}".strip(". ") if (first or last) else None
            if display:
                name_by_id[p["player_id"]] = display

    season = rows[0].get("season")
    week = rows[0].get("week")
    version = rows[0].get("version")
    print(f"{team_upper} Roster — {season} Week {week} (snapshot v{version})")
    print()

    by_group: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        pos = (row.get("depth_chart_position") or "").upper()
        group_label = "OTHER"
        for label, members in _POSITION_GROUPS:
            if pos in members:
                group_label = label
                break
        name = name_by_id.get(row.get("player") or "", row.get("player") or "?")
        by_group[group_label].append(name)

    ordered_labels = [label for label, _ in _POSITION_GROUPS] + ["OTHER"]
    for label in ordered_labels:
        names = sorted(by_group.get(label, []))
        if not names:
            continue
        print(f"  {label:<6} ({len(names):>2})  " + ", ".join(names))

    print()
    print(f"({len(rows)} players total)")
    return True


@handle_cli_errors
def main() -> None:
    parser: argparse.ArgumentParser = setup_cli_parser(
        description=(
            "Load NFL roster data into the database, or view a stored roster "
            "with --show."
        ),
    )
    parser.add_argument(
        "--season",
        type=int,
        help="Season year to load (e.g. 2025). Defaults to the latest season the source dataset has.",
    )
    parser.add_argument(
        "--week",
        type=int,
        help="Week to load (1–18). Defaults to the latest week available in the chosen season.",
    )
    parser.add_argument(
        "--show",
        type=str,
        metavar="TEAM",
        help=(
            "Print the most recent stored roster for TEAM (read-only). "
            "Bypasses fetching and writing."
        ),
    )
    args = parser.parse_args()
    setup_cli_logging(args)
    load_env()

    if args.show:
        return _show_roster(args.show)

    if args.clear:
        logging.getLogger(__name__).info(
            "--clear has no effect on rosters: snapshots are versioned "
            "(is_current=false on prior versions). Continuing without clearing."
        )

    loader = RostersDataLoader()
    fetch_params = {"season": args.season, "week": args.week}
    if maybe_show_columns(loader, args, **fetch_params):
        return True

    result = loader.load_data(dry_run=args.dry_run, clear=False, **fetch_params)
    print_results(result, operation="roster load", dry_run=args.dry_run)
    return True


if __name__ == "__main__":
    main()
