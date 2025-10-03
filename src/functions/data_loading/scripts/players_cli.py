"""
Command‑line interface for loading player metadata.

This script fetches player details from ``nflreadpy`` and upserts them
into the ``players`` table.  Use ``--dry-run`` to preview changes and
``--clear`` to remove existing records before loading new ones.  Pass
``--active-only`` to restrict the dataset to currently active players and
``--min-last-season`` to keep anyone whose last recorded season meets the
threshold.
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
from src.functions.data_loading.core.data.loaders.player import PlayersDataLoader


@handle_cli_errors
def main() -> None:
    parser: argparse.ArgumentParser = setup_cli_parser(
        description="Load NFL player metadata into the database.",
    )
    parser.add_argument(
        "--active-only",
        action="store_true",
        help="Only include players whose status is marked as Active.",
    )
    parser.add_argument(
        "--min-last-season",
        type=int,
        dest="min_last_season",
        help="Restrict players to those with last_season greater than or equal to this value.",
    )
    args = parser.parse_args()
    setup_cli_logging(args)
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
    print_results(result)
    return True


if __name__ == "__main__":
    main()
