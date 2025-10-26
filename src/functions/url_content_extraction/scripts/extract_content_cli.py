"""Command-line entry point for the content extraction service."""

import argparse
import json
from pathlib import Path

from src.functions.url_content_extraction.core.extractors import extractor_factory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract structured content from URLs")
    parser.add_argument("url", help="Target article URL")
    parser.add_argument("--output", type=Path, help="Optional JSON file to write results to")
    parser.add_argument("--force-playwright", action="store_true", help="Force Playwright-backed extraction")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    extractor = extractor_factory.get_extractor(force_playwright=args.force_playwright)
    result = extractor.extract(args.url)
    payload = result.__dict__
    if args.output:
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2))


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
