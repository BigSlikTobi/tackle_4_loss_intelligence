"""Utilities for extracting factual claims from article content."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from src.shared.utils.logging import get_logger

LOGGER = get_logger(__name__)

_NUMBER_PATTERN = re.compile(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?")
_QUOTE_PATTERN = re.compile(r'“[^”]+”|"[^"]+"')
_PLAYER_KEYWORDS = {
    "signed",
    "waived",
    "traded",
    "activated",
    "injury",
    "lineup",
    "starter",
    "rookie",
}
_EVENT_KEYWORDS = {
    "win",
    "loss",
    "defeat",
    "victory",
    "matchup",
    "playoff",
    "game",
    "tournament",
    "final",
}
_STAT_KEYWORDS = {
    "points",
    "yards",
    "touchdowns",
    "rebounds",
    "assists",
    "sacks",
    "interceptions",
    "goals",
}


@dataclass
class ClaimCandidate:
    """Lightweight representation of an extracted claim."""

    text: str
    category: str
    source_field: str
    sentence_index: int

    def to_dict(self) -> dict[str, str | int]:
        return {
            "text": self.text,
            "category": self.category,
            "source_field": self.source_field,
            "sentence_index": self.sentence_index,
        }


def extract_claims(
    article: Mapping[str, object],
    *,
    team_context: Optional[Mapping[str, object]] = None,
    max_sentences: int = 200,
) -> List[ClaimCandidate]:
    """Extract claim candidates from article content.

    Args:
        article: Arbitrary article payload containing structured text.
        team_context: Optional context describing the focus team.
        max_sentences: Safety limit to avoid runaway extraction on long articles.
    """

    flattened = _flatten_article(article)
    claims: list[ClaimCandidate] = []
    team_tokens = _team_tokens(team_context)

    for field_name, sentences in flattened[:max_sentences]:
        for sentence_index, sentence in enumerate(sentences):
            sentence_text = sentence.strip()
            if not sentence_text:
                continue
            category = _classify_sentence(sentence_text, team_tokens)
            if category == "generic":
                continue
            claims.append(
                ClaimCandidate(
                    text=sentence_text,
                    category=category,
                    source_field=field_name,
                    sentence_index=sentence_index,
                )
            )

    LOGGER.debug("Extracted %d candidate claims", len(claims))
    return claims


def _flatten_article(article: Mapping[str, object]) -> List[Tuple[str, List[str]]]:
    flattened: list[Tuple[str, List[str]]] = []
    for key, value in article.items():
        if value is None:
            continue
        if isinstance(value, str):
            flattened.append((key, _split_sentences(value)))
        elif isinstance(value, Mapping):
            nested = _flatten_article(value)
            flattened.extend([(f"{key}.{nested_key}", sentences) for nested_key, sentences in nested])
        elif isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray, Mapping)):
            combined = []
            for index, item in enumerate(value):
                if isinstance(item, str):
                    combined.extend(_split_sentences(item))
                elif isinstance(item, Mapping):
                    nested = _flatten_article(item)
                    flattened.extend([
                        (f"{key}[{index}].{nested_key}", sentences)
                        for nested_key, sentences in nested
                    ])
            if combined:
                flattened.append((key, combined))
    return flattened


def _split_sentences(text: str) -> List[str]:
    text = text.replace("\n", " ")
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def _classify_sentence(sentence: str, team_tokens: Sequence[str]) -> str:
    lower = sentence.lower()

    if _QUOTE_PATTERN.search(sentence):
        return "quote"

    if any(token in lower for token in team_tokens):
        if any(keyword in lower for keyword in _PLAYER_KEYWORDS):
            return "roster"
        if any(keyword in lower for keyword in _EVENT_KEYWORDS):
            return "event"

    if _NUMBER_PATTERN.search(sentence) and any(keyword in lower for keyword in _STAT_KEYWORDS):
        return "statistic"

    # General factual sentence containing numbers or proper nouns
    if _NUMBER_PATTERN.search(sentence) or any(token in lower for token in team_tokens):
        return "factual"

    return "generic"


def _team_tokens(team_context: Optional[Mapping[str, object]]) -> List[str]:
    if not team_context:
        return []
    tokens: List[str] = []
    name_fields = [
        team_context.get("team"),
        team_context.get("team_name"),
        team_context.get("name"),
        team_context.get("nickname"),
    ]
    tokens.extend([str(value).lower() for value in name_fields if value])

    aliases = team_context.get("aliases") if isinstance(team_context, Mapping) else None
    if isinstance(aliases, Iterable) and not isinstance(aliases, (str, bytes, bytearray)):
        tokens.extend(str(alias).lower() for alias in aliases)
    return [token for token in tokens if token]
