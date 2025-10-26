"""Command-line entry point for the content extraction service."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.functions.url_content_extraction.core.extractors import extractor_factory
from src.functions.url_content_extraction.core.contracts.extracted_content import ExtractedContent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract structured content from URLs")
    parser.add_argument("url", help="Target article URL")
    parser.add_argument("--output", type=Path, help="Optional JSON file to write results to")
    parser.add_argument("--timeout", type=int, default=45, help="Network timeout in seconds (default: 45)")
    parser.add_argument("--force-playwright", action="store_true", help="Force Playwright-backed extraction")
    parser.add_argument(
        "--prefer-lightweight",
        action="store_true",
        help="Prefer the lightweight extractor even for heavy hosts",
    )
    parser.add_argument(
        "--pretty",
        dest="pretty",
        action="store_true",
        default=True,
        help="Pretty-print JSON output (default: on)",
    )
    parser.add_argument("--no-pretty", dest="pretty", action="store_false", help="Disable pretty printing")
    parser.add_argument("--log-level", default="INFO", help="Logging level (default: INFO)")
    return parser.parse_args()


def configure_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(levelname)s %(message)s")


def dump_output(payload: dict, *, output: Path | None, pretty: bool) -> None:
    indent = 2 if pretty else None
    serialized = json.dumps(payload, indent=indent, ensure_ascii=False)
    if output:
        output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized)


def make_payload(result: ExtractedContent) -> dict:
    data = asdict(result)

    def _convert(value: object) -> object:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, list):
            return [_convert(item) for item in value]
        if isinstance(value, dict):
            return {key: _convert(val) for key, val in value.items()}
        return value

    return {key: _convert(val) for key, val in data.items()}


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)
    logger = logging.getLogger("extract_content_cli")

    extraction_options = {
        "prefer_lightweight": args.prefer_lightweight,
        "force_playwright": args.force_playwright,
    }

    extractor = extractor_factory.get_extractor(
        args.url,
        force_playwright=args.force_playwright,
        prefer_lightweight=args.prefer_lightweight,
        logger=logger,
    )

    try:
        result = extractor.extract(
            args.url,
            timeout=args.timeout,
            options=extraction_options,
        )
        if (
            result.error
            and not args.force_playwright
            and not args.prefer_lightweight
            and "playwright" in result.error.lower()
        ):
            logger.info("Playwright unavailable; retrying with lightweight extractor")
            fallback_extractor = extractor_factory.get_extractor(
                args.url,
                force_playwright=False,
                prefer_lightweight=True,
                logger=logger,
            )
            result = fallback_extractor.extract(
                args.url,
                timeout=args.timeout,
                options={**extraction_options, "prefer_lightweight": True, "force_playwright": False},
            )
    except Exception as exc:  # pragma: no cover - defensive branch for CLI usage
        logger.error("Extraction failed: %s", exc)
        raise SystemExit(1) from exc

    payload = make_payload(result)
    dump_output(payload, output=args.output, pretty=args.pretty)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    try:
        main()
    except KeyboardInterrupt:  # pragma: no cover - graceful exit for CLI usage
        sys.exit(130)
