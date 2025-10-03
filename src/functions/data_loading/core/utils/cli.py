"""
Simple CLI Helpers
-------------------

This module defines a handful of helper functions that make it easy to
build command‑line interfaces (CLIs) for the various data loaders in this
project.  Each CLI script uses these helpers to parse arguments, set up
logging, print a summary of what happened, and handle errors in a
consistent way.

In plain language, think of this file as the *shared toolkit* for all of
the command‑line programs in this repository:

* **setup_cli_parser** builds a command line parser and automatically
  adds common options like `--dry-run` (show what would happen without
  writing to the database), `--clear` (erase existing data before
  loading), `--verbose` (turn on very chatty logging) and `--log-level`
  (choose how much information is logged).
* **setup_cli_logging** looks at the parsed arguments and configures
  Python’s logging system so that messages are shown at the appropriate
  level.
* **print_results** takes the dictionary returned from a loader and
  prints a human readable summary of what happened – whether records
  were fetched, validated or inserted, and whether the operation was a
  dry run.
* **handle_cli_errors** is a decorator that wraps the main function in
  each CLI script.  It catches common exceptions such as `KeyboardInterrupt`
  or unexpected errors and ensures that the process exits with a sensible
  status code (0 for success, 1 for failure) rather than crashing with a
  stack trace.
* **confirm_action** provides a simple yes/no prompt for actions that
  require confirmation.

These helpers keep the CLI scripts concise and reduce duplication.  Even
if you are new to Python, you can rely on these functions to handle the
boring parts of CLI plumbing so you can focus on what the script is
supposed to do.
"""

import argparse
import json
import sys
from typing import Callable, Any, Dict, Optional

from .logging import setup_logging


def setup_cli_parser(description: str,
                     add_common_args: bool = True) -> argparse.ArgumentParser:
    """Create a standardized CLI argument parser.

    This helper creates an ``argparse.ArgumentParser`` and, by default,
    adds several common arguments that are shared by all loader scripts.
    You can turn off the common arguments by passing ``add_common_args=False``.

    Args:
        description: A short description of what your CLI does.  This
            description is displayed when the user runs the command with
            ``--help``.
        add_common_args: Whether to include the standard flags for dry
            runs, clearing tables, verbose logging and log level.

    Returns:
        A configured ``ArgumentParser`` ready for your script to add
        additional arguments.
    """
    parser = argparse.ArgumentParser(description=description)

    if add_common_args:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without actually doing it"
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing data before loading"
        )
        parser.add_argument(
            "--verbose", "-v",
            action="store_true",
            help="Enable verbose logging"
        )
        parser.add_argument(
            "--log-level",
            choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            default="INFO",
            help="Set logging level"
        )
        parser.add_argument(
            "--show-columns",
            action="store_true",
            help="Print available columns from the upstream dataset and exit",
        )

    return parser


def handle_cli_errors(func: Callable) -> Callable:
    """Decorator to handle common CLI errors and normalize exit codes.

    Wrapping your ``main`` function in this decorator ensures that the
    script doesn’t crash ungracefully.  It will catch a
    ``KeyboardInterrupt`` (when a user presses Ctrl+C) and unexpected
    exceptions, print a friendly message to the console and return an
    exit code of 1.  Successful runs return 0.

    Args:
        func: The main CLI function to wrap.

    Returns:
        A wrapped function that can be called in ``if __name__ == '__main__'``.
    """
    def wrapper(*args, **kwargs) -> int:
        try:
            result = func(*args, **kwargs)
            # Normalize to exit code semantics: 0 on success, 1 on failure
            return 0 if bool(result) else 1
        except KeyboardInterrupt:
            print("\nOperation cancelled by user")
            return 1
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            return 1

    return wrapper


def setup_cli_logging(args: argparse.Namespace) -> None:
    """Set up logging based on CLI arguments.

    This helper reads the ``--verbose`` and ``--log-level`` flags from
    the parsed arguments and configures the project’s logging system
    accordingly via :func:`src.core.utils.logging.setup_logging`.

    Args:
        args: Parsed command line arguments, typically returned from
            :func:`setup_cli_parser`.
    """
    log_level = "DEBUG" if getattr(args, 'verbose', False) else getattr(args, 'log_level', 'INFO')
    setup_logging(level=log_level)


def print_results(result: Dict[str, Any],
                  operation: str = "operation",
                  dry_run: bool = False) -> None:
    """Print standardized results from a data load operation.

    Most loader classes return a dictionary summarising what happened.
    This function looks at that dictionary and prints a friendly summary
    for the user.  It handles both dry runs (where nothing is actually
    written) and real runs, and includes counts of fetched and validated
    records where available.

    Args:
        result: Result dictionary from the loader.
        operation: Name of the operation for display purposes.
        dry_run: Whether this was a dry run; controls which fields are
            printed.
    """
    if hasattr(result, "to_dict"):
        result = result.to_dict()

    if result.get("success"):
        if dry_run:
            print(f"DRY RUN - Would perform {operation}")
            if "would_upsert" in result:
                print(f"Would upsert {result['would_upsert']} records")
            if "would_clear" in result:
                print(f"Would clear table: {result['would_clear']}")
            if "records_processed" in result:
                print(f"Prepared records: {result['records_processed']}")
            if "sample_record" in result and result["sample_record"]:
                print(f"Sample record: {result['sample_record']}")
        else:
            print(f"✅ Successfully completed {operation}")
            if "total_fetched" in result:
                print(f"Fetched: {result['total_fetched']} records")
            if "total_validated" in result:
                print(f"Validated: {result['total_validated']} records")
            if "records_processed" in result:
                print(f"Processed: {result['records_processed']} records")
            if "records_written" in result:
                print(f"Written: {result['records_written']} records")
            if "upsert_result" in result and "affected_rows" in result["upsert_result"]:
                print(f"Upserted: {result['upsert_result']['affected_rows']} records")
            if "messages" in result:
                for message in result["messages"]:
                    print(message)
    else:
        error_msg = result.get("error", result.get("message", "Unknown error"))
        print(f"❌ {operation.capitalize()} failed: {error_msg}")


def maybe_show_columns(loader: Any,
                       args: argparse.Namespace,
                       **fetch_params: Any) -> bool:
    """Print available columns for the dataset if ``--show-columns`` is set."""

    if not getattr(args, "show_columns", False):
        return False

    info = loader.inspect(**fetch_params)
    columns = info.get("columns", [])
    dtypes = info.get("dtypes", {})
    sample = info.get("sample", [])
    rowcount = info.get("rowcount")

    print(f"Columns ({len(columns)} total):")
    for column in columns:
        dtype = dtypes.get(column, "unknown")
        print(f" - {column} ({dtype})")

    if rowcount is not None:
        print(f"\nEstimated rows: {rowcount}")

    if sample:
        print("\nSample record:")
        formatted = json.dumps(sample[0], indent=2, default=str)
        print(formatted)

    return True

def confirm_action(message: str, default: bool = False) -> bool:
    """Ask the user for confirmation via the console.

    Useful for actions that might be destructive (like clearing a table).
    The function prints a prompt like “Are you sure? [y/N]” and returns
    True or False depending on the user’s input.

    Args:
        message: Confirmation message to display.
        default: Default value if the user just presses Enter.

    Returns:
        True if the user confirms, False otherwise.
    """
    suffix = " [Y/n]" if default else " [y/N]"
    response = input(f"{message}{suffix}: ").strip().lower()

    if not response:
        return default

    return response in ['y', 'yes', 'true', '1']
