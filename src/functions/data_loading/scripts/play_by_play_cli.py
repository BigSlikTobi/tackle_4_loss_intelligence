"""
Command‑line interface for loading play-by-play data.

Specify a season and optionally a week to fetch play-by-play records.
Use ``--dry-run`` to preview the number of plays and ``--clear`` to 
purge existing rows before reloading.
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
from src.functions.data_loading.core.data.loaders.game import PlayByPlayDataLoader


@handle_cli_errors
def main() -> None:
    parser: argparse.ArgumentParser = setup_cli_parser(
        description="Load play-by-play data into the database.",
    )
    parser.add_argument("--season", type=int, required=True, help="Season year to load (e.g. 2024)")
    parser.add_argument("--week", type=int, help="Specific week to load (1–22)")
    args = parser.parse_args()
    setup_cli_logging(args)
    loader = PlayByPlayDataLoader()
    fetch_params = {"season": args.season, "week": args.week}
    if maybe_show_columns(loader, args, **fetch_params):
        return True
    result = loader.load_data(dry_run=args.dry_run, clear=args.clear, **fetch_params)
    print_results(result)
    return True


if __name__ == "__main__":
    main()
