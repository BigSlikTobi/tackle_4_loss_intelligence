"""Submit an article extraction job to a running /submit endpoint."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.utils.env import load_env


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Base URL of the deployed service (without /submit)")
    src_group = parser.add_mutually_exclusive_group(required=True)
    src_group.add_argument("--text", help="Raw article text")
    src_group.add_argument("--input", type=Path, help="Path to a UTF-8 article file")
    parser.add_argument("--article-id")
    parser.add_argument("--title")
    parser.add_argument("--article-url")
    parser.add_argument("--max-topics", type=int, default=5)
    parser.add_argument("--max-entities", type=int, default=15)
    parser.add_argument("--confidence-threshold", type=float, default=0.6)
    parser.add_argument("--no-resolve", action="store_true")
    parser.add_argument("--openai-key", help="OpenAI API key (falls back to OPENAI_API_KEY)")
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--supabase-url")
    parser.add_argument("--supabase-key")
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    load_env()
    text = args.text if args.text is not None else args.input.read_text(encoding="utf-8")

    openai_key = args.openai_key or os.getenv("OPENAI_API_KEY")
    sb_url = args.supabase_url or os.getenv("SUPABASE_URL")
    sb_key = args.supabase_key or os.getenv("SUPABASE_KEY")
    if not openai_key or not sb_url or not sb_key:
        print("Missing credentials (need OpenAI and Supabase).", file=sys.stderr)
        return 2

    payload = {
        "article": {
            "text": text,
            "article_id": args.article_id,
            "title": args.title,
            "url": args.article_url,
        },
        "options": {
            "max_topics": args.max_topics,
            "max_entities": args.max_entities,
            "resolve_entities": not args.no_resolve,
            "confidence_threshold": args.confidence_threshold,
        },
        "llm": {"provider": "openai", "model": args.model, "api_key": openai_key},
        "supabase": {"url": sb_url, "key": sb_key},
    }

    response = requests.post(
        args.url.rstrip("/") + "/submit",
        json=payload,
        timeout=args.timeout,
    )
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    return 0 if response.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
