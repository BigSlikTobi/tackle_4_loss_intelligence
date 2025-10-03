"""
Command‑line interface for loading team metadata.

Run this script to download the latest team information from
``nflreadpy`` and insert it into your configured database.  Use the
``--dry-run`` flag to see how many records would be loaded without
actually performing any database writes.
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
from src.functions.data_loading.core.data.loaders.team import TeamsDataLoader


@handle_cli_errors
def main() -> None:
    parser: argparse.ArgumentParser = setup_cli_parser(
        description="Load NFL team metadata into the database.",
    )
    parser.add_argument(
        "--season",
        type=int,
        help="Season year to filter team metadata (if supported by upstream dataset).",
    )
    args = parser.parse_args()
    setup_cli_logging(args)
    loader = TeamsDataLoader()
    fetch_params = {"season": args.season}
    if maybe_show_columns(loader, args, **fetch_params):
        return True
    result = loader.load_data(dry_run=args.dry_run, clear=args.clear, **fetch_params)
    print_results(result)
    return True


if __name__ == "__main__":
    main()
