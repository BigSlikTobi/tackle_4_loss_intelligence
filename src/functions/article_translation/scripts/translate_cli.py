"""Command-line entry point for translating team articles."""

import argparse
import json
from pathlib import Path

from src.functions.article_translation.core.contracts.translated_article import TranslationRequest
from src.functions.article_translation.core.llm.openai_translator import OpenAITranslationClient
from src.functions.article_translation.core.processors.structure_validator import validate_structure
from src.functions.article_translation.core.processors.term_preserver import preserve_terms


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Translate team articles into other languages")
    parser.add_argument("input", type=Path, help="JSON file containing the English article")
    parser.add_argument("--output", type=Path, help="Optional JSON file to write the translated article")
    parser.add_argument("--language", default="de", help="Target language code")
    parser.add_argument("--model", default="gpt-5-mini-flex", help="OpenAI model identifier")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    request = TranslationRequest(
        language=args.language,
        headline=payload["headline"],
        sub_header=payload["sub_header"],
        introduction_paragraph=payload["introduction_paragraph"],
        content=payload.get("content", []),
    )
    preserved = preserve_terms(request)
    client = OpenAITranslationClient(model=args.model)
    translation = client.translate(preserved)
    validated = validate_structure(translation)
    output = json.dumps(validated.__dict__, indent=2)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
