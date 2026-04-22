"""Local end-to-end article knowledge extraction CLI.

Runs the in-process pipeline without the job store — useful for prompt tuning
and local smoke tests. Accepts an article either via --text or --input FILE,
and prints the resulting topics + entities as JSON to stdout.

Examples:
    python -m src.functions.article_knowledge_extraction.scripts.extract_article_knowledge_cli \\
        --input sample.txt

    python -m src.functions.article_knowledge_extraction.scripts.extract_article_knowledge_cli \\
        --text "Josh Allen threw..." --no-resolve --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path when invoked as a script
PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging

from src.functions.article_knowledge_extraction.core.config import (
    ArticleInput,
    ExtractionOptions,
    LLMConfig,
)
from src.functions.article_knowledge_extraction.core.pipelines.article_extraction_pipeline import (
    ArticleExtractionPipeline,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    src_group = parser.add_mutually_exclusive_group(required=True)
    src_group.add_argument("--text", help="Raw article text to analyze")
    src_group.add_argument("--input", type=Path, help="Path to a UTF-8 article file")

    parser.add_argument("--article-id", help="Optional caller-supplied article id")
    parser.add_argument("--title", help="Optional article title")
    parser.add_argument("--url", help="Optional source URL")

    parser.add_argument("--max-topics", type=int, default=5)
    parser.add_argument("--max-entities", type=int, default=15)
    parser.add_argument("--confidence-threshold", type=float, default=0.6)
    parser.add_argument(
        "--no-resolve",
        action="store_true",
        help="Skip entity resolution against Supabase (useful for prompt tuning)",
    )

    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--api-key", help="OpenAI API key (falls back to OPENAI_API_KEY)")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--max-retries", type=int, default=2)

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run extraction but do not call the LLM — prints the prompts that would be sent",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--output", type=Path, help="Write JSON result to this path instead of stdout")
    return parser.parse_args()


def _read_article(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text
    return args.input.read_text(encoding="utf-8")


def main() -> int:
    args = _parse_args()
    load_env()
    setup_logging(level="DEBUG" if args.verbose else os.getenv("LOG_LEVEL", "INFO"))
    logger = logging.getLogger(__name__)

    article = ArticleInput(
        text=_read_article(args),
        article_id=args.article_id,
        title=args.title,
        url=args.url,
    )
    try:
        article.validate()
    except ValueError as exc:
        logger.error("Invalid article: %s", exc)
        return 2

    options = ExtractionOptions(
        max_topics=args.max_topics,
        max_entities=args.max_entities,
        resolve_entities=not args.no_resolve,
        confidence_threshold=args.confidence_threshold,
    )
    options.validate()

    if args.dry_run:
        from src.functions.article_knowledge_extraction.core.prompts import (
            build_entity_prompt,
            build_topic_prompt,
        )

        payload = {
            "dry_run": True,
            "article": {
                "article_id": article.article_id,
                "title": article.title,
                "url": article.url,
                "length": len(article.text),
            },
            "options": options.__dict__,
            "topic_prompt": build_topic_prompt(article.text, options.max_topics),
            "entity_prompt": build_entity_prompt(article.text, options.max_entities),
        }
        _emit(payload, args.output)
        return 0

    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OpenAI API key required (pass --api-key or set OPENAI_API_KEY)")
        return 2

    llm = LLMConfig(
        provider="openai",
        model=args.model,
        api_key=api_key,
        timeout_seconds=args.timeout,
        max_retries=args.max_retries,
    )
    pipeline = ArticleExtractionPipeline.from_llm_config(llm, options)
    try:
        result = pipeline.run(article, options)
    except Exception:
        logger.exception("Pipeline failed")
        return 1

    _emit(result.to_dict(), args.output)
    return 0


def _emit(payload, out_path) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    if out_path is None:
        print(text)
    else:
        out_path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
