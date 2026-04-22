"""POST a URL extraction job to the deployed /submit endpoint.

Examples:
    python -m src.functions.url_content_extraction_service.scripts.submit_job_cli \\
        --url https://submit-fn-url \\
        --supabase-url $SUPABASE_URL --supabase-key $SUPABASE_KEY \\
        --target-url https://example.com/article
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.utils.env import load_env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Submit endpoint URL")
    parser.add_argument(
        "--target-url",
        action="append",
        required=True,
        help="URL to extract (repeat for multiple)",
    )
    parser.add_argument("--supabase-url", default=os.getenv("SUPABASE_URL"))
    parser.add_argument("--supabase-key", default=os.getenv("SUPABASE_KEY"))
    parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument("--force-playwright", action="store_true")
    args = parser.parse_args()

    load_env()
    if not args.supabase_url or not args.supabase_key:
        print("supabase url + key are required", file=sys.stderr)
        return 2

    payload = {
        "urls": args.target_url,
        "options": {
            "timeout_seconds": args.timeout_seconds,
            "force_playwright": args.force_playwright,
        },
        "supabase": {"url": args.supabase_url, "key": args.supabase_key},
    }

    import requests

    response = requests.post(
        args.url, json=payload, headers={"Content-Type": "application/json"}, timeout=30
    )
    print(f"HTTP {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2))
    except ValueError:
        print(response.text)
    return 0 if response.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
