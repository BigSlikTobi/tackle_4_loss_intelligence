"""Poll a submitted job by id. Optionally wait until terminal."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.utils.env import load_env


_TERMINAL = {"succeeded", "failed"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Base URL of the deployed service (without /poll)")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--supabase-url")
    parser.add_argument("--supabase-key")
    parser.add_argument("--wait", action="store_true", help="Poll until terminal or timeout")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between polls")
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    load_env()
    sb_url = args.supabase_url or os.getenv("SUPABASE_URL")
    sb_key = args.supabase_key or os.getenv("SUPABASE_KEY")
    if not sb_url or not sb_key:
        print("Missing Supabase credentials.", file=sys.stderr)
        return 2

    payload = {
        "job_id": args.job_id,
        "supabase": {"url": sb_url, "key": sb_key},
    }
    poll_url = args.url.rstrip("/") + "/poll"
    deadline = time.time() + args.timeout_seconds

    while True:
        response = requests.post(poll_url, json=payload, timeout=15.0)
        data = response.json() if response.content else {}
        status = (data.get("status") or "").lower()
        print(json.dumps(data, indent=2, ensure_ascii=False))

        if not args.wait:
            return 0 if response.ok else 1
        if status in _TERMINAL or response.status_code == 404:
            return 0 if status == "succeeded" else 1
        if time.time() > deadline:
            print("Timed out waiting for terminal status.", file=sys.stderr)
            return 1
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
