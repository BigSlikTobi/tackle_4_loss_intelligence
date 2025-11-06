"""CLI tool to run knowledge extraction on manual text payloads."""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Bootstrap project root to allow absolute imports
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.knowledge_extraction.core.extraction.entity_extractor import (
    EntityExtractor,
    ExtractedEntity,
)
from src.functions.knowledge_extraction.core.extraction.topic_extractor import (
    TopicExtractor,
    ExtractedTopic,
)

logger = logging.getLogger(__name__)


class MockEntity(ExtractedEntity):
    """Simple mock entity for offline demonstrations."""


class MockTopic(ExtractedTopic):
    """Simple mock topic for offline demonstrations."""


def parse_args() -> argparse.Namespace:
    """Set up CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the knowledge extraction models against a manual payload and "
            "display the resulting topics and entities."
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


def _mock_results(text: str) -> Dict[str, List[Any]]:
    """Generate deterministic mock topics/entities for offline use."""
    _ = text  # The mock does not depend on content beyond logging.
    topics = [
        MockTopic(topic="team performance & trends", confidence=0.88, rank=1),
        MockTopic(topic="player profiles & interviews", confidence=0.64, rank=2),
    ]
    entities = [
        MockEntity(
            entity_type="team",
            mention_text="Buffalo Bills",
            team_abbr="BUF",
            rank=1,
        ),
        MockEntity(
            entity_type="player",
            mention_text="Josh Allen",
            position="QB",
            team_abbr="BUF",
            rank=2,
        ),
    ]
    return {"topics": topics, "entities": entities}


def _run_extraction(
    text: str,
    max_topics: Optional[int],
    max_entities: Optional[int],
    use_mock: bool,
) -> Dict[str, List[Any]]:
    """Run topic/entity extraction using either real or mock models."""
    if use_mock:
        logger.warning("Using mock extraction results (no API calls will be made).")
        return _mock_results(text)

    entity_extractor = EntityExtractor()
    topic_extractor = TopicExtractor()

    if max_topics is None:
        max_topics = int(os.getenv("MAX_TOPICS_PER_GROUP", "10"))
    if max_entities is None:
        max_entities = int(os.getenv("MAX_ENTITIES_PER_GROUP", "20"))

    topics = topic_extractor.extract(text, max_topics=max_topics)
    entities = entity_extractor.extract(text, max_entities=max_entities)

    return {"topics": topics, "entities": entities}


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


def main() -> None:
    args = parse_args()
    setup_logging(level=args.log_level)
    load_env()

    try:
        payload = _load_payload(Path(args.input).resolve(), args.index)
        text = payload.get("text", "").strip()
        if not text:
            raise ValueError("The payload does not contain text to analyse.")

        extraction = _run_extraction(
            text=text,
            max_topics=args.max_topics,
            max_entities=args.max_entities,
            use_mock=args.mock,
        )
        topics = extraction["topics"]
        entities = extraction["entities"]

    except Exception as exc:
        logger.error(str(exc))
        sys.exit(1)

    print("\n" + "=" * 70)
    print("KNOWLEDGE EXTRACTION RESULTS")
    print("=" * 70)
    print(f"Input type: {payload.get('input_type', 'unknown')}")
    if payload.get("title"):
        print(f"Title: {payload['title']}")
    print(f"Characters analysed: {len(text)}")
    print("\nTopics:")
    print(_format_topics(topics))
    print("\nEntities:")
    print(_format_entities(entities))
    print("=" * 70 + "\n")

    if args.output:
        output_path = Path(args.output).resolve()
        result = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "input": {
                "input_type": payload.get("input_type"),
                "title": payload.get("title"),
            },
            "topics": _serialize_topics(topics),
            "entities": _serialize_entities(entities),
        }
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Extraction results saved to %s", output_path)


if __name__ == "__main__":
    main()
