"""
CLI for loading roster data.

By default the loader identifies the latest season/week snapshot
available from ``nflreadpy`` and upserts that roster into the database.
Provide ``--season`` and optionally ``--week`` to target a specific
snapshot.
"""

from __future__ import annotations

import argparse
import logging

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
from src.functions.data_loading.core.data.loaders.player import RostersDataLoader


@handle_cli_errors
def main() -> None:
    parser: argparse.ArgumentParser = setup_cli_parser(
        description="Load NFL roster data into the database.",
    )
    parser.add_argument(
        "--season",
        type=int,
        help="Season year to load (e.g. 2024). Defaults to the most recent season available.",
    )
    parser.add_argument(
        "--week",
        type=int,
        help="Specific week to load (1–18). Defaults to the latest available week for the chosen season.",
    )
    args = parser.parse_args()
    setup_cli_logging(args)
    loader = RostersDataLoader()
    fetch_params = {"season": args.season, "week": args.week}
    if maybe_show_columns(loader, args, **fetch_params):
        return True
    clear_flag = args.clear or not args.dry_run
    if clear_flag and not args.clear and not args.dry_run:
        logging.getLogger(__name__).info(
            "Clearing existing roster rows before insert (default behaviour)."
        )
    result = loader.load_data(dry_run=args.dry_run, clear=clear_flag, **fetch_params)
    print_results(result)
    return True


if __name__ == "__main__":
    main()
