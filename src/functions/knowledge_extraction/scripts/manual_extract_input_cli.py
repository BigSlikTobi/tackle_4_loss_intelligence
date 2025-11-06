"""CLI tool to capture manual text input for knowledge extraction."""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

# Bootstrap project root on path for shared utilities
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.shared.utils.logging import setup_logging

logger = logging.getLogger(__name__)


def _read_text(args: argparse.Namespace) -> str:
    """Read text from the provided source."""
    sources = [bool(args.text), bool(args.file), bool(args.stdin)]
    if sum(sources) != 1:
        raise ValueError(
            "Provide exactly one of --text, --file, or --stdin for input text."
        )

    if args.text:
        return args.text

    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            raise FileNotFoundError(f"Input file not found: {file_path}")
        return file_path.read_text(encoding="utf-8")

    logger.info("Reading text from standard input. Press Ctrl+D (Unix) or Ctrl+Z (Windows) when done.")
    return sys.stdin.read()


def _build_payload(args: argparse.Namespace, text: str) -> Dict[str, Any]:
    """Build the JSON payload representing the manual extraction request."""
    cleaned_text = text.strip()
    if not cleaned_text:
        raise ValueError("Input text is empty after trimming whitespace.")

    return {
        "input_type": args.input_type,
        "title": args.title,
        "text": cleaned_text,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "metadata": {
            "source": "stdin" if args.stdin else ("arg" if args.text else "file"),
            "file_path": str(Path(args.file).resolve()) if args.file else None,
        },
    }


def parse_args() -> argparse.Namespace:
    """Configure and parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Prepare manual text input for knowledge extraction.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="Raw text to analyse.")
    group.add_argument("--file", type=str, help="Path to a file containing the text.")
    group.add_argument(
        "--stdin",
        action="store_true",
        help="Read the text content from standard input.",
    )

    parser.add_argument(
        "--title",
        type=str,
        help="Optional title describing the article or summary.",
    )
    parser.add_argument(
        "--input-type",
        choices=["article", "summary"],
        default="summary",
        help="Type of content being analysed.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="manual_extraction_input.json",
        help="Path where the prepared payload JSON will be written.",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to the output file if it already exists (maintains a JSON list).",
    )

    return parser.parse_args()


def save_payload(payload: Dict[str, Any], output_path: Path, append: bool) -> None:
    """Persist the payload to disk."""
    if append and output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Cannot append to {output_path}: existing file is not valid JSON."
            ) from exc

        if isinstance(existing, list):
            existing.append(payload)
            content = existing
        else:
            content = [existing, payload]
    else:
        content = payload

    output_path.write_text(
        json.dumps(content, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    setup_logging(level="INFO")

    try:
        text = _read_text(args)
        payload = _build_payload(args, text)
        output_path = Path(args.output).resolve()
        save_payload(payload, output_path, args.append)
    except Exception as exc:
        logger.error(str(exc))
        sys.exit(1)

    logger.info("Manual extraction payload saved to %s", output_path)
    print(f"Saved manual extraction payload to {output_path}")


if __name__ == "__main__":
    main()
