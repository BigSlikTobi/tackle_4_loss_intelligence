"""CLI for loading and viewing NFL depth charts.

Two modes:

* Default: fetch the current league-wide depth chart from nflreadpy and
  persist a versioned snapshot. Each call creates a new version per
  (season, week, team); previous versions are flagged ``is_current=false``.

* ``--show TEAM``: print the most recent stored depth chart for a single
  team in a human-readable format. Read-only — does not write to the
  database.

Notes:
    The depth chart source (nflreadpy / nflverse) only ever returns the
    *current* depth chart. The ``--snapshot-week`` flag tags the snapshot
    with a week number for versioning purposes; it does NOT filter the
    source data to a historical week.
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
from src.functions.data_loading.core.utils.season import (  # noqa: E402
    get_current_season,
    get_current_week_and_season_type,
)
from src.functions.data_loading.core.data.loaders.player import (  # noqa: E402
    DepthChartsDataLoader,
)


# Position display order for `--show` (offense → defense → special teams).
_POSITION_DISPLAY_ORDER = [
    "QB", "RB", "FB", "WR", "TE", "OL", "C", "G", "T", "LT", "LG", "RG", "RT",
    "DL", "DT", "DE", "NT", "EDGE",
    "LB", "ILB", "OLB", "MLB",
    "DB", "CB", "S", "FS", "SS", "NB",
    "K", "P", "LS", "KR", "PR",
]


def _show_depth_chart(team: str) -> bool:
    """Print the most recent stored depth chart for `team` and return True."""

    from src.shared.db.connection import get_supabase_client

    team_upper = team.upper()
    client = get_supabase_client()

    response = (
        client.table("depth_charts")
        .select(
            "team, season, week, version, pos_grp, pos_name, pos_abb, "
            "pos_slot, pos_rank, player_id"
        )
        .eq("team", team_upper)
        .eq("is_current", True)
        .execute()
    )
    rows: List[Dict[str, Any]] = getattr(response, "data", None) or []

    if not rows:
        print(f"No current depth chart found for team {team_upper}.")
        return True

    # Resolve player names in a single batched lookup.
    player_ids = sorted({r["player_id"] for r in rows if r.get("player_id")})
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
    print(f"{team_upper} Depth Chart — {season} Week {week} (snapshot v{version})")
    print()

    # Group by position abbreviation, then sort within group by pos_rank.
    by_pos: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        pos = (row.get("pos_abb") or row.get("pos_name") or "?").upper()
        by_pos[pos].append(row)

    def _rank_int(row: Dict[str, Any]) -> int:
        try:
            return int(str(row.get("pos_rank") or "99"))
        except ValueError:
            return 99

    seen_positions = set(by_pos.keys())
    ordered: List[str] = [p for p in _POSITION_DISPLAY_ORDER if p in seen_positions]
    ordered += sorted(seen_positions - set(_POSITION_DISPLAY_ORDER))

    for pos in ordered:
        entries = sorted(by_pos[pos], key=_rank_int)
        cells = []
        for entry in entries[:6]:
            rank = entry.get("pos_rank") or "?"
            name = name_by_id.get(entry.get("player_id") or "", entry.get("player_id") or "?")
            cells.append(f"{rank}. {name}")
        print(f"  {pos:<5} " + "   ".join(cells))

    print()
    print(f"({len(rows)} total entries)")
    return True


@handle_cli_errors
def main() -> None:
    parser: argparse.ArgumentParser = setup_cli_parser(
        description=(
            "Load NFL depth chart data into the database, or view a stored "
            "depth chart with --show."
        ),
    )
    parser.add_argument(
        "--team",
        type=str,
        help="Team abbreviation to filter the load by (e.g. NYJ).",
    )
    parser.add_argument(
        "--show",
        type=str,
        metavar="TEAM",
        help=(
            "Print the most recent stored depth chart for TEAM (read-only). "
            "Bypasses fetching and writing."
        ),
    )
    parser.add_argument(
        "--season",
        type=int,
        default=None,
        help="Season year to fetch. Defaults to the current NFL season.",
    )
    parser.add_argument(
        "--snapshot-week",
        type=int,
        default=None,
        dest="snapshot_week",
        help=(
            "Week number to TAG this snapshot with for versioning. Does NOT "
            "filter source data — the source only returns the current depth "
            "chart. Defaults to the current NFL week."
        ),
    )
    args = parser.parse_args()
    setup_cli_logging(args)
    load_env()

    if args.show:
        return _show_depth_chart(args.show)

    if args.season is None:
        args.season = get_current_season()
    if args.snapshot_week is None:
        args.snapshot_week, _ = get_current_week_and_season_type()

    if args.clear:
        logging.getLogger(__name__).info(
            "--clear has no effect on depth charts: snapshots are versioned "
            "(is_current=false on prior versions). Continuing without clearing."
        )

    loader = DepthChartsDataLoader()
    fetch_params = {
        "team": args.team,
        "season": args.season,
        "week": args.snapshot_week,
    }
    if maybe_show_columns(loader, args, **fetch_params):
        return True

    result = loader.load_data(
        dry_run=args.dry_run,
        clear=False,
        **fetch_params,
    )
    print_results(result, operation="depth chart load", dry_run=args.dry_run)
    return True


if __name__ == "__main__":
    main()
