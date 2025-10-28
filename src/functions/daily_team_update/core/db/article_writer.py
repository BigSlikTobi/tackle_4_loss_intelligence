"""Article persistence helpers for the daily team update pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from .team_reader import TeamRecord
from ..integration.supabase_client import SupabaseClient


class ArticleWriter:
    """Handles persistence of generated and translated team articles."""

    def __init__(self, client: SupabaseClient, *, dry_run: bool = False) -> None:
        self._client = client
        self._dry_run = dry_run

    def persist_article(
        self,
        *,
        team: TeamRecord,
        language: str,
        article: Dict[str, Any],
        source_urls: Iterable[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist an article and return the stored row."""

        _ = metadata  # Metadata currently unused due to minimal table schema
        _ = source_urls  # Source URLs stored elsewhere; retained for interface compatibility

        payload = self._build_payload(
            team=team,
            language=language,
            article=article,
        )
        if self._dry_run:
            return {**payload, "id": "dry-run"}
        return self._client.upsert_article(payload)

    def _build_payload(
        self,
        *,
        team: TeamRecord,
        language: str,
        article: Dict[str, Any],
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        paragraphs = article.get("content")
        if isinstance(paragraphs, list):
            cleaned = [str(paragraph).strip() for paragraph in paragraphs if paragraph]
        elif isinstance(paragraphs, str):
            cleaned = [paragraphs.strip()]
        else:
            cleaned = []
        content_text = "\n\n".join(filter(None, cleaned))

        payload: Dict[str, Any] = {
            "team": team.abbreviation,
            "language": language,
            "headline": article.get("headline"),
            "sub_headline": article.get("sub_header")
            or article.get("subHeader")
            or article.get("sub_headline"),
            "introduction": article.get("introduction_paragraph")
            or article.get("introductionParagraph")
            or article.get("introduction"),
            "content": content_text,
            "created_at": now.isoformat(),
        }
        return payload
