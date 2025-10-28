"""CLI for selecting article images using the image_selection module."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging

from src.functions.image_selection.core.factory import request_from_payload
from src.functions.image_selection.core.service import ImageSelectionService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select Creative Commons images for an article.")
    parser.add_argument("--config", type=Path, help="Path to JSON payload matching the HTTP API.")
    parser.add_argument("--article-text", help="Raw article text input.")
    parser.add_argument("--article-file", type=Path, help="File containing article text.")
    parser.add_argument("--query", help="Override search query and skip LLM.")
    parser.add_argument("--num-images", type=int, default=1, help="Number of images to produce.")
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM optimization.")
    parser.add_argument("--llm-provider", default="gemini", help="LLM provider (gemini|openai).")
    parser.add_argument("--llm-model", help="LLM model identifier.")
    parser.add_argument("--llm-api-key", help="LLM API key.")
    parser.add_argument("--llm-param", action="append", default=[], help="LLM parameter k=v (repeatable).")
    parser.add_argument("--search-api-key", help="Google Custom Search API key.")
    parser.add_argument("--search-engine-id", help="Google Programmable Search Engine ID.")
    parser.add_argument("--search-rights", default="cc_publicdomain,cc_attribute,cc_sharealike")
    parser.add_argument("--search-image-type", default="photo")
    parser.add_argument("--search-image-size", default="large")
    parser.add_argument("--supabase-url", help="Supabase project URL.")
    parser.add_argument("--supabase-key", help="Supabase service role key.")
    parser.add_argument("--supabase-bucket", default="images")
    parser.add_argument("--supabase-table", default="article_images")
    parser.add_argument("--output", type=Path, help="Optional path to write JSON response.")
    return parser.parse_args()


def load_payload(args: argparse.Namespace) -> Dict[str, Any]:
    if args.config:
        with args.config.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if args.article_file and "article_text" not in payload:
            payload["article_text"] = args.article_file.read_text(encoding="utf-8")
        if args.article_text:
            payload.setdefault("article_text", args.article_text)
        return payload

    article_text = collect_article_text(args)
    search_api_key = (
        args.search_api_key
        or os.getenv("GOOGLE_CUSTOM_SEARCH_KEY")
        or os.getenv("Custom_Search_API_KEY")
    )
    search_engine_id = args.search_engine_id or os.getenv("GOOGLE_CUSTOM_SEARCH_ENGINE_ID")

    payload: Dict[str, Any] = {
        "article_text": article_text,
        "query": args.query,
        "num_images": args.num_images,
        "enable_llm": not args.no_llm,
    }

    supabase_url = args.supabase_url or os.getenv("SUPABASE_URL")
    supabase_key = args.supabase_key or os.getenv("SUPABASE_KEY")
    if supabase_url or supabase_key:
        if not supabase_url or not supabase_key:
            raise ValueError(
                "Both Supabase URL and key are required when enabling Supabase persistence"
            )
        payload["supabase"] = {
            "url": supabase_url,
            "key": supabase_key,
            "bucket": args.supabase_bucket,
            "table": args.supabase_table,
        }
    else:
        logging.info(
            "Supabase credentials not provided; results will return original image URLs only."
        )

    if search_api_key and search_engine_id:
        payload["search"] = {
            "api_key": search_api_key,
            "engine_id": search_engine_id,
            "rights": args.search_rights,
            "image_type": args.search_image_type,
            "image_size": args.search_image_size,
        }
    elif search_api_key or search_engine_id:
        raise ValueError(
            "Both --search-api-key and --search-engine-id are required when enabling Google Custom Search"
        )

    if not args.no_llm:
        payload["llm"] = {
            "provider": args.llm_provider,
            "model": args.llm_model,
            "api_key": args.llm_api_key,
            "parameters": parse_parameters(args.llm_param),
        }

    return payload


def collect_article_text(args: argparse.Namespace) -> Optional[str]:
    text_parts: List[str] = []
    if args.article_file:
        text_parts.append(args.article_file.read_text(encoding="utf-8"))
    if args.article_text:
        text_parts.append(args.article_text)
    if text_parts:
        return "\n".join(part.strip() for part in text_parts if part.strip())
    return None


def parse_parameters(param_items: List[str]) -> Dict[str, Any]:
    parameters: Dict[str, Any] = {}
    for item in param_items:
        if "=" not in item:
            raise ValueError(f"Invalid llm-param '{item}' expected key=value")
        key, raw_value = item.split("=", 1)
        parameters[key] = coerce_value(raw_value)
    return parameters


def coerce_value(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


async def run_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    request_model = request_from_payload(payload)
    service = ImageSelectionService(request_model)
    results = await service.process()
    return {
        "status": "success",
        "query": service.resolved_query
        or request_model.explicit_query
        or request_model.article_text,
        "count": len(results),
        "images": [
            {
                "id": item.record_id,
                "image_url": item.public_url,
                "original_url": item.original_url,
                "author": item.author,
                "source": item.source,
                "width": item.width,
                "height": item.height,
                "title": item.title,
                "record_id": item.record_id,
            }
            for item in results
        ],
    }


def main() -> None:
    args = parse_args()
    load_env()
    setup_logging(level="INFO")

    try:
        payload = load_payload(args)
        response = asyncio.run(run_request(payload))
    except Exception as exc:  # noqa: BLE001
        logging.error("Image selection failed: %s", exc, exc_info=True)
        raise SystemExit(1) from exc

    output_text = json.dumps(response, indent=2)
    if args.output:
        args.output.write_text(output_text + "\n", encoding="utf-8")
        logging.info("Wrote response to %s", args.output)
    else:
        print(output_text)


if __name__ == "__main__":
    main()
