"""Narrative analysis utilities."""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from ..contracts.team_article import SummaryBundle

_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "from",
    "this",
    "game",
    "team",
    "season",
    "have",
    "will",
    "their",
}


def _tokenize(text: str) -> Iterable[str]:
    for token in text.lower().split():
        cleaned = "".join(character for character in token if character.isalpha())
        if len(cleaned) <= 3 or cleaned in _STOP_WORDS:
            continue
        yield cleaned


def find_central_narrative(bundle: SummaryBundle) -> str:
    """Identify key storyline from summaries using keyword frequency."""

    all_text = " ".join(bundle.summaries)
    counter = Counter(_tokenize(all_text))
    if not counter:
        return ""
    most_common = ", ".join(word for word, _ in counter.most_common(3))
    return f"Central themes: {most_common}."
