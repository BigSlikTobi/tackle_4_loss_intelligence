"""
CLI for loading weekly player statistics.

You must specify the ``--season`` to load data for and may optionally
specify ``--week`` to restrict the load to a single week.  Use
``--dry-run`` to see how many records would be loaded without writing
them to the database.
"""

from __future__ import annotations

import argparse

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))



from src.functions.data_loading.core.utils.cli import (
    setup_cli_parser,
    setup_cli_logging,
    print_results,
    maybe_show_columns,
    handle_cli_errors,
)
from src.functions.data_loading.core.data.loaders.player import PlayerWeeklyStatsDataLoader


@handle_cli_errors
def main() -> None:
    parser: argparse.ArgumentParser = setup_cli_parser(
        description="Load weekly NFL player statistics into the database.",
    )
    parser.add_argument("--season", required=True, type=int, help="Season year to load (e.g. 2024)")
    parser.add_argument("--week", type=int, help="Specific week to load (1–18)")
    args = parser.parse_args()
    setup_cli_logging(args)
    loader = PlayerWeeklyStatsDataLoader()
    fetch_params = {"season": args.season, "week": args.week}
    if maybe_show_columns(loader, args, **fetch_params):
        return True
    result = loader.load_data(dry_run=args.dry_run, clear=args.clear, **fetch_params)
    print_results(result)
    return True


if __name__ == "__main__":
    main()
