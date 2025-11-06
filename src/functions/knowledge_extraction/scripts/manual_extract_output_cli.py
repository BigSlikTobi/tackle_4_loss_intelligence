"""CLI tool to run the full knowledge extraction pipeline on manual payloads."""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Bootstrap project root to allow absolute imports
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.knowledge_extraction.core.extraction.entity_extractor import (
    ExtractedEntity,
)
from src.functions.knowledge_extraction.core.extraction.topic_extractor import (
    ExtractedTopic,
)
from src.functions.knowledge_extraction.core.resolution.entity_resolver import (
    ResolvedEntity,
)
from src.functions.knowledge_extraction.scripts.extract_knowledge_cli import (
    ManualExtractionResult,
    run_manual_extraction,
)

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Set up CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Execute the knowledge extraction pipeline against a manual payload and "
            "display the resulting topics, entities, and resolved entities."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input",
        type=str,
        default="manual_extraction_input.json",
        help="Path to the manual payload JSON produced by manual_extract_input_cli.py.",
    )
    parser.add_argument(
        "--index",
        type=int,
        default=0,
        help="Index of the payload to process when the file contains a list.",
    )
    parser.add_argument(
        "--max-topics",
        type=int,
        default=None,
        help="Maximum number of topics to request from the model.",
    )
    parser.add_argument(
        "--max-entities",
        type=int,
        default=None,
        help="Maximum number of entities to request from the model.",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Optional path to write the extraction results as JSON.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help=(
            "Use deterministic mock results instead of calling the OpenAI API. "
            "Useful for demonstrations without credentials."
        ),
    )
    parser.add_argument(
        "--no-resolve",
        action="store_true",
        help="Skip entity resolution (avoids Supabase lookups).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level for the CLI.",
    )
    return parser.parse_args()


def _load_payload(path: Path, index: int) -> Dict[str, Any]:
    """Load the manual payload from disk."""
    if not path.exists():
        raise FileNotFoundError(
            f"Manual extraction payload not found at {path}. "
            "Run manual_extract_input_cli.py first."
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse JSON payload from {path}: {exc}") from exc

    if isinstance(data, list):
        if not data:
            raise ValueError("The payload list is empty; provide new input with the input CLI.")
        if index < 0 or index >= len(data):
            raise IndexError(
                f"Index {index} is out of range for payload list of size {len(data)}."
            )
        return data[index]

    if index not in (0, None):
        raise IndexError("Index must be 0 when payload is a single object.")

    return data


def _format_topics(topics: List[ExtractedTopic]) -> str:
    """Pretty print topics for console output."""
    if not topics:
        return "  (no topics identified)"

    lines = []
    for topic in topics:
        rank = topic.rank if topic.rank is not None else "-"
        confidence = (
            f" ({topic.confidence:.2f})" if topic.confidence is not None else ""
        )
        lines.append(f"  [{rank}] {topic.topic}{confidence}")
    return "\n".join(lines)


def _format_entities(entities: List[ExtractedEntity]) -> str:
    """Pretty print entities for console output."""
    if not entities:
        return "  (no entities identified)"

    lines = []
    for entity in entities:
        bits = [f"[{entity.entity_type}] {entity.mention_text}"]
        if entity.position:
            bits.append(entity.position)
        if entity.team_abbr:
            bits.append(entity.team_abbr)
        if entity.team_name:
            bits.append(entity.team_name)
        if entity.rank is not None:
            bits.append(f"rank {entity.rank}")
        if entity.confidence is not None:
            bits.append(f"confidence {entity.confidence:.2f}")
        if entity.context:
            bits.append(f"context: {entity.context}")
        lines.append("  " + " | ".join(bits))
    return "\n".join(lines)


def _format_resolved_entities(
    entities: List[ResolvedEntity],
    resolution_requested: bool,
) -> str:
    """Pretty print resolved entities for console output."""
    if entities:
        lines: List[str] = []
        for entity in entities:
            bits = [
                f"[{entity.entity_type}] {entity.matched_name}",
                f"id={entity.entity_id}",
            ]
            if entity.confidence is not None:
                bits.append(f"confidence {entity.confidence:.2f}")
            if entity.rank is not None:
                bits.append(f"rank {entity.rank}")
            if entity.mention_text and entity.mention_text != entity.matched_name:
                bits.append(f"mention: {entity.mention_text}")
            if entity.position:
                bits.append(entity.position)
            if entity.team_abbr:
                bits.append(entity.team_abbr)
            if entity.team_name:
                bits.append(entity.team_name)
            lines.append("  " + " | ".join(bits))
        return "\n".join(lines)

    if not resolution_requested:
        return "  (resolution skipped)"
    return "  (no entities resolved)"


def _serialize_topics(topics: List[ExtractedTopic]) -> List[Dict[str, Any]]:
    """Convert topic dataclasses into JSON-serialisable dicts."""
    serialised: List[Dict[str, Any]] = []
    for topic in topics:
        serialised.append(
            {
                "topic": topic.topic,
                "confidence": topic.confidence,
                "rank": topic.rank,
            }
        )
    return serialised


def _serialize_entities(entities: List[ExtractedEntity]) -> List[Dict[str, Any]]:
    """Convert entity dataclasses into JSON-serialisable dicts."""
    serialised: List[Dict[str, Any]] = []
    for entity in entities:
        serialised.append(
            {
                "entity_type": entity.entity_type,
                "mention_text": entity.mention_text,
                "context": entity.context,
                "confidence": entity.confidence,
                "is_primary": entity.is_primary,
                "rank": entity.rank,
                "position": entity.position,
                "team_abbr": entity.team_abbr,
                "team_name": entity.team_name,
            }
        )
    return serialised


def _serialize_resolved_entities(
    entities: List[ResolvedEntity],
) -> List[Dict[str, Any]]:
    """Convert resolved entity dataclasses into JSON-serialisable dicts."""
    serialised: List[Dict[str, Any]] = []
    for entity in entities:
        serialised.append(
            {
                "entity_type": entity.entity_type,
                "entity_id": entity.entity_id,
                "matched_name": entity.matched_name,
                "mention_text": entity.mention_text,
                "confidence": entity.confidence,
                "is_primary": entity.is_primary,
                "rank": entity.rank,
                "position": entity.position,
                "team_abbr": entity.team_abbr,
                "team_name": entity.team_name,
            }
        )
    return serialised


def _print_results(
    payload: Dict[str, Any],
    result: ManualExtractionResult,
    resolution_requested: bool,
) -> None:
    """Output the extraction results to stdout."""
    print("\n" + "=" * 70)
    print("KNOWLEDGE EXTRACTION RESULTS")
    print("=" * 70)
    print(f"Input type: {result.input_type or 'unknown'}")
    if result.title:
        print(f"Title: {result.title}")
    print(f"Characters analysed: {result.text_length}")
    if payload.get("metadata"):
        print(f"Metadata: {json.dumps(payload['metadata'], ensure_ascii=False)}")

    print("\nTopics:")
    print(_format_topics(result.topics))

    print("\nEntities:")
    print(_format_entities(result.entities))

    print("\nResolved Entities:")
    print(_format_resolved_entities(result.resolved_entities, resolution_requested))

    summary = result.summary()
    print("\nSummary:")
    print(
        f"  topics: {summary['topics_extracted']}, "
        f"entities: {summary['entities_extracted']}, "
        f"resolved: {summary['resolved_entities']}"
    )
    print("=" * 70 + "\n")


def main() -> None:
    args = parse_args()
    setup_logging(level=args.log_level)
    load_env()

    try:
        payload = _load_payload(Path(args.input).resolve(), args.index)
        result = run_manual_extraction(
            payload=payload,
            max_topics=args.max_topics,
            max_entities=args.max_entities,
            use_mock=args.mock,
            resolve_entities=not args.no_resolve,
        )
    except Exception as exc:
        logger.error(str(exc))
        sys.exit(1)

    _print_results(payload, result, resolution_requested=not args.no_resolve)

    if args.output:
        output_path = Path(args.output).resolve()
        output_payload = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "input": {
                "input_type": result.input_type,
                "title": result.title,
                "characters": result.text_length,
            },
            "summary": result.summary(),
            "topics": _serialize_topics(result.topics),
            "entities": _serialize_entities(result.entities),
            "resolved_entities": _serialize_resolved_entities(result.resolved_entities),
            "metadata": result.metadata,
            "mock_run": args.mock,
            "resolution_requested": not args.no_resolve,
        }
        output_path.write_text(
            json.dumps(output_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Extraction results saved to %s", output_path)


if __name__ == "__main__":
    main()
