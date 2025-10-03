"""
CLI for loading depth chart data.

Depth charts describe the player order at each position on a team.  Use
``--team`` to load the depth chart for a single team or omit it to load
the latest charts for all teams.  As with other loaders you can use
``--dry-run`` and ``--clear`` flags to control behaviour.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.functions.data_loading.core.utils.cli import (
    setup_cli_parser,
    setup_cli_logging,
    print_results,
    maybe_show_columns,
    handle_cli_errors,
)
from src.functions.data_loading.core.data.loaders.player import DepthChartsDataLoader


@handle_cli_errors
def main() -> None:
    parser: argparse.ArgumentParser = setup_cli_parser(
        description="Load NFL depth chart data into the database.",
    )
    parser.add_argument("--team", type=str, help="Team abbreviation to filter by (e.g. NYJ)")
    parser.add_argument(
        "--season",
        type=int,
        help="Season year to fetch when the data source requires it (default: current year).",
    )
    args = parser.parse_args()
    setup_cli_logging(args)
    loader = DepthChartsDataLoader()
    fetch_params = {
        "team": args.team,
        "season": args.season,
    }
    if maybe_show_columns(loader, args, **fetch_params):
        return True
    clear_flag = args.clear or not args.dry_run
    if clear_flag and not args.clear and not args.dry_run:
        logging.getLogger(__name__).info(
            "Clearing existing depth chart rows before insert (default behaviour)."
        )
    result = loader.load_data(
        dry_run=args.dry_run,
        clear=clear_flag,
        **fetch_params,
    )
    print_results(result)
    return True


if __name__ == "__main__":
    main()
