"""Command-line entry point for generating team articles."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.functions.team_article_generation.core.contracts.team_article import GenerationOptions, SummaryBundle
from src.functions.team_article_generation.core.llm.openai_client import OpenAIGenerationClient
from src.shared.utils.env import load_env


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a team article from summaries")
    parser.add_argument("input", type=Path, help="JSON file containing team abbreviation and summaries list")
    parser.add_argument("--output", type=Path, help="Optional JSON file for the generated article")
    default_model = os.getenv("OPENAI_TEAM_MODEL", GenerationOptions().model)
    parser.add_argument("--model", default=default_model, help="OpenAI model identifier")
    parser.add_argument("--temperature", type=float, help="Sampling temperature override")
    parser.add_argument("--service-tier", default=None, help="Override OpenAI service tier (default: flex)")
    parser.add_argument("--max-output-tokens", type=int, help="Override maximum output tokens")
    parser.add_argument("--timeout", type=int, help="Request timeout in seconds (default: configured value)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_env()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    summaries = payload.get("summaries") or payload.get("content")
    if isinstance(summaries, str):
        summaries = [summaries]
    if not summaries:
        raise SystemExit("Input payload must include 'summaries' or 'content'")
    team_abbr = payload.get("team_abbr") or payload.get("team") or "UNK"
    bundle = SummaryBundle(
        team_abbr=team_abbr,
        team_name=payload.get("team_name"),
        summaries=summaries,
    )
    options = GenerationOptions(model=args.model)
    overrides = {}
    if args.temperature is not None:
        overrides["temperature"] = args.temperature
    if args.service_tier:
        overrides["service_tier"] = args.service_tier
    if args.max_output_tokens is not None:
        overrides["max_output_tokens"] = args.max_output_tokens
    if args.timeout is not None:
        overrides["request_timeout_seconds"] = args.timeout
    if overrides:
        options = GenerationOptions(**{**options.model_dump(), **overrides})

    client = OpenAIGenerationClient(model=options.model)
    article = client.generate(bundle, options=options)
    output = json.dumps(article.model_dump(), indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
