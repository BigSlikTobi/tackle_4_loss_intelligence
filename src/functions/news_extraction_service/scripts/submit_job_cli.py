"""POST a news extraction job to the deployed /submit endpoint.

Examples:
    python -m src.functions.news_extraction_service.scripts.submit_job_cli \\
        --url https://submit-fn-url \\
        --supabase-url $SUPABASE_URL --supabase-key $SUPABASE_KEY \\
        --source-filter ESPN --since 2026-04-22T00:00:00+00:00
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
    parser.add_argument("--supabase-url", default=os.getenv("SUPABASE_URL"))
    parser.add_argument("--supabase-key", default=os.getenv("SUPABASE_KEY"))
    parser.add_argument("--source-filter", default=None)
    parser.add_argument(
        "--since",
        default=None,
        help="ISO 8601 timestamp (with timezone) — return items published "
             "on or after this instant. Example: 2026-04-22T10:00:00+00:00",
    )
    parser.add_argument("--max-articles", type=int, default=None)
    parser.add_argument("--max-workers", type=int, default=None)
    args = parser.parse_args()

    load_env()
    if not args.supabase_url or not args.supabase_key:
        print("supabase url + key are required", file=sys.stderr)
        return 2

    options = {
        k: v
        for k, v in {
            "source_filter": args.source_filter,
            "since": args.since,
            "max_articles": args.max_articles,
            "max_workers": args.max_workers,
        }.items()
        if v is not None
    }
    payload = {
        "options": options,
        "supabase": {"url": args.supabase_url, "key": args.supabase_key},
    }

    import requests

    response = requests.post(
        args.url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    print(f"HTTP {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2))
    except ValueError:
        print(response.text)
    return 0 if response.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
