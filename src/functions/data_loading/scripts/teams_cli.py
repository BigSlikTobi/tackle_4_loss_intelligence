"""CLI for loading NFL team metadata.

Run this to download team information from nflreadpy (32 NFL franchises:
abbreviations, names, conferences, divisions, colors) and upsert them into
the ``teams`` table. Use ``--dry-run`` to preview without writing,
``--clear`` to wipe the table before reloading.
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
from src.functions.data_loading.core.data.loaders.team import TeamsDataLoader  # noqa: E402


def _print_team_rollup() -> None:
    """Read the teams table and print a conference/division summary."""
    from src.shared.db.connection import get_supabase_client

    client = get_supabase_client()
    response = (
        client.table("teams")
        .select("team_abbr, team_name, team_conference, team_division")
        .execute()
    )
    rows: List[Dict[str, Any]] = getattr(response, "data", None) or []
    if not rows:
        print("(teams table is empty after load)")
        return

    by_division: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        conf = (row.get("team_conference") or "?").strip().upper()
        div = (row.get("team_division") or "?").strip()
        abbr = (row.get("team_abbr") or "??").strip().upper()
        by_division[f"{conf} {div}".strip()].append(abbr)

    confs = Counter((row.get("team_conference") or "?").strip().upper() for row in rows)
    print(
        f"Loaded {len(rows)} teams across {len(confs)} conferences "
        f"({', '.join(sorted(confs))}), {len(by_division)} divisions:"
    )
    for division in sorted(by_division):
        members = sorted(by_division[division])
        print(f"  {division:<12}  {', '.join(members)}")


@handle_cli_errors
def main() -> None:
    parser: argparse.ArgumentParser = setup_cli_parser(
        description="Load NFL team metadata into the database.",
    )
    args = parser.parse_args()
    setup_cli_logging(args)
    load_env()

    loader = TeamsDataLoader()
    if maybe_show_columns(loader, args):
        return True

    result = loader.load_data(dry_run=args.dry_run, clear=args.clear)
    print_results(result, operation="teams load", dry_run=args.dry_run)

    if not args.dry_run and getattr(result, "success", True):
        try:
            _print_team_rollup()
        except Exception as exc:  # pragma: no cover - summary is best-effort
            print(f"(skipped post-load summary: {exc})")
    return True


if __name__ == "__main__":
    main()
