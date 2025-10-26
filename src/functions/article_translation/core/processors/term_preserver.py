"""Extract and preserve key terms for translation prompts."""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

from ..contracts.translated_article import TranslationRequest

_COMMON_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "game",
    "season",
    "team",
    "coach",
    "match",
    "league",
}


def _iter_candidate_terms(text: str) -> Iterable[str]:
    pattern = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b")
    for match in pattern.finditer(text):
        candidate = match.group(1)
        normalized = candidate.strip()
        if normalized.lower() in _COMMON_WORDS:
            continue
        if len(normalized.split()) > 4:
            continue
        yield normalized


def preserve_terms(request: TranslationRequest) -> TranslationRequest:
    """Augment the request with proper nouns to keep untranslated."""

    combined = "\n".join(
        [request.headline, request.sub_header, request.introduction_paragraph, *request.content]
    )
    counter = Counter(_iter_candidate_terms(combined))
    # Keep top 12 most frequent proper nouns
    preserved = sorted({term for term, _ in counter.most_common(12)})
    if not preserved:
        return request
    return request.model_copy(update={"preserve_terms": preserved})
