"""Command-line helper for the summarization service."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.functions.article_summarization.core.contracts.summary import SummarizationOptions, SummarizationRequest
from src.functions.article_summarization.core.llm.gemini_client import GeminiSummarizationClient
from src.functions.article_summarization.core.processors.summary_formatter import format_summary
from src.shared.utils.env import load_env


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize extracted article content")
    parser.add_argument("input", type=Path, help="Path to a JSON file containing article content")
    parser.add_argument("--output", type=Path, help="Optional JSON file to write the summary to")
    default_model = os.getenv("GEMINI_MODEL", SummarizationOptions().model)
    parser.add_argument("--model", default=default_model, help="Gemini model identifier")
    parser.add_argument("--team", help="Team name for prompt personalization")
    parser.add_argument("--temperature", type=float, default=0.2, help="Generation temperature (default: 0.2)")
    parser.add_argument("--top-p", type=float, default=0.9, help="top_p nucleus sampling value (default: 0.9)")
    parser.add_argument("--max-output-tokens", type=int, default=512, help="Maximum tokens in summary (default: 512)")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs without calling Gemini")
    parser.add_argument("--pretty", dest="pretty", action="store_true", default=True, help="Pretty-print JSON output")
    parser.add_argument("--no-pretty", dest="pretty", action="store_false", help="Disable pretty printing")
    parser.add_argument("--log-level", default="INFO", help="Logging level (default: INFO)")
    return parser.parse_args()


def load_article_content(payload: dict) -> str:
    """Resolve article text from various extractor payload shapes."""

    content = payload.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        candidate = "\n\n".join(section for section in content if isinstance(section, str))
        if candidate.strip():
            return candidate

    paragraphs = payload.get("paragraphs")
    if isinstance(paragraphs, list):
        cleaned = [paragraph.strip() for paragraph in paragraphs if isinstance(paragraph, str) and paragraph.strip()]
        if cleaned:
            return "\n\n".join(cleaned)

    raise ValueError("Input JSON must include non-empty 'content' or 'paragraphs'")


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(message)s")
    logger = logging.getLogger("summarize_cli")

    load_env()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    try:
        article_text = load_article_content(payload)
    except ValueError as exc:
        logger.error("Invalid input payload: %s", exc)
        raise SystemExit(1) from exc
    request = SummarizationRequest(
        article_id=payload.get("article_id") or payload.get("url"),
        team_name=args.team or payload.get("team_name"),
        content=article_text,
    )

    options = SummarizationOptions(
        model=args.model,
        temperature=args.temperature,
        top_p=args.top_p,
        max_output_tokens=args.max_output_tokens,
    )

    if args.dry_run:
        logger.info("Dry-run successful for article %s", request.article_id)
        return

    client = GeminiSummarizationClient(model=args.model, logger=logger)
    summary = client.summarize(request, options=options)
    formatted = format_summary(summary, options=options)
    output = json.dumps(formatted.model_dump(), indent=2 if args.pretty else None, ensure_ascii=False)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    try:
        main()
    except KeyboardInterrupt:  # pragma: no cover - CLI convenience
        sys.exit(130)
