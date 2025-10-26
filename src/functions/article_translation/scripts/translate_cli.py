"""Command-line entry point for translating team articles."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.functions.article_translation.core.contracts.translated_article import (
    TranslationOptions,
    TranslationRequest,
)
from src.functions.article_translation.core.llm.openai_translator import OpenAITranslationClient
from src.functions.article_translation.core.processors.structure_validator import validate_structure
from src.functions.article_translation.core.processors.term_preserver import preserve_terms
from src.shared.utils.env import load_env


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Translate team articles into other languages")
    parser.add_argument("input", type=Path, help="JSON file containing the English article")
    parser.add_argument("--output", type=Path, help="Optional JSON file to write the translated article")
    parser.add_argument("--language", default="de", help="Target language code (default: de)")
    default_model = os.getenv("OPENAI_TRANSLATION_MODEL", TranslationOptions().model)
    parser.add_argument("--model", default=default_model, help="OpenAI model identifier")
    parser.add_argument("--temperature", type=float, help="Sampling temperature when supported")
    parser.add_argument("--max-output-tokens", type=int, help="Maximum output tokens when supported")
    parser.add_argument("--service-tier", help="OpenAI service tier override (default: flex)")
    parser.add_argument("--timeout", type=int, help="Request timeout in seconds (default: 600)")
    return parser.parse_args()


def build_options(args: argparse.Namespace) -> TranslationOptions:
    options = TranslationOptions(model=args.model)
    overrides = {}
    if args.temperature is not None:
        overrides["temperature"] = args.temperature
    if args.max_output_tokens is not None:
        overrides["max_output_tokens"] = args.max_output_tokens
    if args.service_tier:
        overrides["service_tier"] = args.service_tier
    if args.timeout is not None:
        overrides["request_timeout_seconds"] = args.timeout
    if overrides:
        options = TranslationOptions(**{**options.model_dump(), **overrides})
    return options


def main() -> None:
    args = parse_args()
    load_env()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    request = TranslationRequest(
        article_id=payload.get("article_id") or payload.get("source_article_id"),
        language=args.language,
        headline=payload["headline"],
        sub_header=payload["sub_header"],
        introduction_paragraph=payload["introduction_paragraph"],
        content=payload.get("content", []),
    )

    preserved_request = preserve_terms(request)
    options = build_options(args)
    client = OpenAITranslationClient(model=options.model)
    translation = client.translate(preserved_request, options=options)
    validated = validate_structure(translation, reference=preserved_request)

    output = json.dumps(validated.model_dump(), indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    try:
        main()
    except KeyboardInterrupt:  # pragma: no cover - graceful exit
        sys.exit(130)
