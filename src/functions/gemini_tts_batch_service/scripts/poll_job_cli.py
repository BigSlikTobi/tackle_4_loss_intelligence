"""POST to the /poll endpoint, with optional --wait until terminal.

Examples:
    python -m src.functions.gemini_tts_batch_service.scripts.poll_job_cli \\
        --url https://poll-fn-url --job-id <uuid> --wait
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.utils.env import load_env


def main() -> int:
    load_env()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Poll endpoint URL")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--supabase-url", default=os.getenv("SUPABASE_URL"))
    parser.add_argument("--supabase-key", default=os.getenv("SUPABASE_KEY"))
    parser.add_argument(
        "--bearer-token",
        default=os.getenv("TTS_BATCH_FUNCTION_AUTH_TOKEN"),
    )
    parser.add_argument("--wait", action="store_true", help="Poll until terminal")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    args = parser.parse_args()

    if not args.supabase_url or not args.supabase_key:
        print("supabase url + key are required", file=sys.stderr)
        return 2

    import requests

    payload = {
        "job_id": args.job_id,
        "supabase": {"url": args.supabase_url, "key": args.supabase_key},
    }
    headers = {"Content-Type": "application/json"}
    if args.bearer_token:
        headers["Authorization"] = f"Bearer {args.bearer_token}"

    deadline = time.monotonic() + args.max_seconds

    while True:
        response = requests.post(args.url, json=payload, headers=headers, timeout=30)
        print(f"HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            print(response.text)
            return 1
        print(json.dumps(body, indent=2))

        status = body.get("status")
        terminal = status in ("succeeded", "failed", "error")
        if terminal or not args.wait:
            return 0 if status == "succeeded" else (1 if status in ("failed", "error") else 0)
        if time.monotonic() > deadline:
            print(f"Timed out after {args.max_seconds}s", file=sys.stderr)
            return 124
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
