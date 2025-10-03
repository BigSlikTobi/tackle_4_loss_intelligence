"""Command-line interface for assembling downstream data packages."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.functions.data_loading.core.packaging.service import assemble_package
from src.functions.data_loading.core.utils.cli import handle_cli_errors, setup_cli_logging, setup_cli_parser


@handle_cli_errors
def main() -> bool:
    parser = setup_cli_parser(
        description="Build a standardized data package for downstream consumers.",
        add_common_args=False,
    )
    parser.add_argument(
        "--request",
        "-r",
        required=True,
        help="Path to a JSON file describing the package request.",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Optional path to write the package envelope JSON.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output (indent=2).",
    )
    args = parser.parse_args()
    setup_cli_logging(args)

    request_path = Path(args.request)
    if not request_path.exists():
        raise FileNotFoundError(f"Request file not found: {request_path}")

    with request_path.open("r", encoding="utf-8") as handle:
        request_payload = json.load(handle)

    package = assemble_package(request_payload)
    package_dict = package.to_dict()

    json_kwargs = (
        {"indent": 2, "ensure_ascii": False}
        if args.pretty
        else {"separators": (",", ":"), "ensure_ascii": False}
    )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(package_dict, handle, **json_kwargs)
            if args.pretty:
                handle.write("\n")
    else:
        json.dump(package_dict, sys.stdout, **json_kwargs)
        sys.stdout.write("\n")

    print(f"✅ Package built: {package.package_id}")
    return True


if __name__ == "__main__":
    main()
