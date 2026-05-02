"""POST a TTS batch job to the deployed /submit endpoint.

Examples:
    # Create a Gemini batch from a JSON file describing items.
    python -m src.functions.gemini_tts_batch_service.scripts.submit_job_cli \\
        --url https://submit-fn-url \\
        --action create \\
        --payload-file request.json

    # Check status of an existing Gemini batch.
    python -m src.functions.gemini_tts_batch_service.scripts.submit_job_cli \\
        --url https://submit-fn-url \\
        --action status \\
        --batch-id batches/abc123

    # Process a completed batch and upload MP3s to a chosen bucket.
    python -m src.functions.gemini_tts_batch_service.scripts.submit_job_cli \\
        --url https://submit-fn-url \\
        --action process \\
        --batch-id batches/abc123 \\
        --bucket audio --path-prefix gemini-tts-batch
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
    load_env()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Submit endpoint URL")
    parser.add_argument(
        "--action",
        required=True,
        choices=["create", "status", "process"],
    )
    parser.add_argument(
        "--payload-file",
        help="JSON file containing the body for action=create (model_name, voice_name, items)",
    )
    parser.add_argument("--batch-id", help="Required for status/process")
    parser.add_argument("--bucket", default="audio", help="Storage bucket for action=process")
    parser.add_argument(
        "--path-prefix",
        default="gemini-tts-batch",
        help="Storage path prefix for action=process",
    )
    parser.add_argument("--supabase-url", default=os.getenv("SUPABASE_URL"))
    parser.add_argument("--supabase-key", default=os.getenv("SUPABASE_KEY"))
    parser.add_argument(
        "--bearer-token",
        default=os.getenv("TTS_BATCH_FUNCTION_AUTH_TOKEN"),
        help="Caller bearer token (Authorization: Bearer ...)",
    )
    args = parser.parse_args()

    if not args.supabase_url or not args.supabase_key:
        print("supabase url + key are required", file=sys.stderr)
        return 2

    payload: dict = {
        "action": args.action,
        "supabase": {"url": args.supabase_url, "key": args.supabase_key},
    }

    if args.action == "create":
        if not args.payload_file:
            print("--payload-file is required for action=create", file=sys.stderr)
            return 2
        with open(args.payload_file, "r", encoding="utf-8") as handle:
            body = json.load(handle)
        payload["model_name"] = body.get("model_name", "")
        payload["voice_name"] = body.get("voice_name", "Charon")
        payload["items"] = body.get("items", [])
    elif args.action == "status":
        if not args.batch_id:
            print("--batch-id is required for action=status", file=sys.stderr)
            return 2
        payload["batch_id"] = args.batch_id
    else:  # process
        if not args.batch_id:
            print("--batch-id is required for action=process", file=sys.stderr)
            return 2
        payload["batch_id"] = args.batch_id
        payload["storage"] = {"bucket": args.bucket, "path_prefix": args.path_prefix}

    import requests

    headers = {"Content-Type": "application/json"}
    if args.bearer_token:
        headers["Authorization"] = f"Bearer {args.bearer_token}"

    response = requests.post(args.url, json=payload, headers=headers, timeout=30)
    print(f"HTTP {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2))
    except ValueError:
        print(response.text)
    return 0 if response.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
