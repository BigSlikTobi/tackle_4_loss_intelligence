"""Command-line interface for loading NFL injury reports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.functions.data_loading.core.utils.cli import (  # noqa: E402
    handle_cli_errors,
    maybe_show_columns,
    print_results,
    setup_cli_logging,
    setup_cli_parser,
)
from src.functions.data_loading.core.data.loaders.injury import (  # noqa: E402
    InjuriesDataLoader,
)


_SEASON_TYPE_CHOICES = ["reg", "pre", "post"]


@handle_cli_errors
def main() -> None:
    parser: argparse.ArgumentParser = setup_cli_parser(
        description="Load NFL injury updates into the Supabase database.",
    )
    parser.add_argument(
        "--season",
        type=int,
        required=True,
        help="Season year to load (e.g. 2025)",
    )
    parser.add_argument(
        "--week",
        type=int,
        required=True,
        help="Specific week to scrape (1-18 for regular season)",
    )
    parser.add_argument(
        "--season-type",
        choices=_SEASON_TYPE_CHOICES,
        default="reg",
        help="Season phase to scrape (pre, reg, post)",
    )
    args = parser.parse_args()
    setup_cli_logging(args)

    loader = InjuriesDataLoader()
    fetch_params = {
        "season": args.season,
        "week": args.week,
        "season_type": args.season_type,
    }

    if maybe_show_columns(loader, args, **fetch_params):
        return True

    result = loader.load_data(
        dry_run=args.dry_run,
        clear=args.clear,
        **fetch_params,
    )
    print_results(result, operation="injury load", dry_run=args.dry_run)
    return True


if __name__ == "__main__":
    main()
