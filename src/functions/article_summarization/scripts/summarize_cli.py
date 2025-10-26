"""Command-line helper for the summarization service."""

import argparse
import json
from pathlib import Path

from src.functions.article_summarization.core.contracts.summary import SummarizationRequest
from src.functions.article_summarization.core.llm.gemini_client import GeminiSummarizationClient
from src.functions.article_summarization.core.processors.summary_formatter import format_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize extracted article content")
    parser.add_argument("input", type=Path, help="Path to a JSON file containing article content")
    parser.add_argument("--output", type=Path, help="Optional JSON file to write the summary to")
    parser.add_argument("--model", default="gemma-3n", help="Gemini model identifier")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    request = SummarizationRequest(article_id=payload.get("article_id"), content=payload["content"])
    client = GeminiSummarizationClient(model=args.model)
    summary = client.summarize(request)
    formatted = format_summary(summary)
    output = json.dumps(formatted.__dict__, indent=2)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
