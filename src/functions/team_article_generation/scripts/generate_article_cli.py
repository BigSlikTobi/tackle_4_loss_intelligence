"""Command-line entry point for generating team articles."""

import argparse
import json
from pathlib import Path

from src.functions.team_article_generation.core.contracts.team_article import GeneratedArticle, SummaryBundle
from src.functions.team_article_generation.core.llm.openai_client import OpenAIGenerationClient
from src.functions.team_article_generation.core.processors.article_validator import validate_article


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a team article from summaries")
    parser.add_argument("input", type=Path, help="JSON file containing team abbreviation and summaries list")
    parser.add_argument("--output", type=Path, help="Optional JSON file for the generated article")
    parser.add_argument("--model", default="gpt-5-flex", help="OpenAI model identifier")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    bundle = SummaryBundle(team_abbr=payload["team_abbr"], summaries=payload.get("summaries", []))
    client = OpenAIGenerationClient(model=args.model)
    article = client.generate(bundle)
    validated = validate_article(article)
    output = json.dumps(validated.__dict__, indent=2)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
