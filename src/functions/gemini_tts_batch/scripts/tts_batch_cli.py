import argparse
import json
import sys
from pathlib import Path

import requests

try:
    from . import _bootstrap  # type: ignore  # noqa: F401
except ImportError:
    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.shared.utils.env import load_env


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Call the Gemini TTS batch Cloud Function")
    parser.add_argument(
        "--payload-file",
        type=Path,
        required=True,
        help="Path to a JSON request payload containing action=create|status|process",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8080",
        help="Function URL",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=None,
        help="Optional file to write the JSON response to",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_env()
    payload = json.loads(args.payload_file.read_text(encoding="utf-8"))
    response = requests.post(args.url, json=payload, timeout=120)

    if response.headers.get("content-type", "").startswith("application/json"):
        body = response.json()
        rendered = json.dumps(body, indent=2)
    else:
        rendered = response.text

    print(f"Status: {response.status_code}")
    print(rendered)

    if args.output_file:
        args.output_file.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
