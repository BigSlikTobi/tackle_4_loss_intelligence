"""Relationship persistence helpers for articles and images."""

from __future__ import annotations

import logging
from typing import Dict, Iterable, Optional

from ..integration.supabase_client import SupabaseClient


logger = logging.getLogger(__name__)


class RelationshipManager:
    """Creates links between persisted articles and stored images."""

    def __init__(self, client: SupabaseClient, *, dry_run: bool = False) -> None:
        self._client = client
        self._dry_run = dry_run

    def link_articles_to_images(
        self,
        *,
        english_article_id: str,
        translated_article_id: Optional[str],
        image_records: Iterable[dict],
    ) -> None:
        """Persist relationship rows for supplied image records."""

        if self._dry_run:
            return

        resolved_ids = []
        for image in image_records:
            if not isinstance(image, dict):
                continue
            identifier = self._extract_identifier(image)
            if not identifier:
                identifier = self._persist_image_record(image)
            if identifier:
                resolved_ids.append(identifier)

        if not resolved_ids:
            logger.info("No image identifiers resolved for article %s", english_article_id)
            return

        deduplicated = list(dict.fromkeys(resolved_ids))
        self._client.link_article_images(
            english_article_id,
            translated_article_id,
            deduplicated,
        )

    @staticmethod
    def _extract_identifier(image: Dict) -> Optional[str]:
        for key in ("id", "image_id", "uuid", "record_id"):
            value = image.get(key)
            if value:
                return str(value)
        return None

    def _persist_image_record(self, image: Dict) -> Optional[str]:
        image_url = (
            image.get("image_url")
            or image.get("public_url")
            or image.get("url")
        )
        if not image_url:
            logger.debug("Skipping image without URL while creating record: %s", image)
            return None

        payload = {
            "image_url": image_url,
            "original_url": image.get("original_url") or image.get("source_url") or image_url,
            "author": image.get("author") or "",
            "source": image.get("source") or "",
        }

        try:
            record = self._client.record_image(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist image metadata for %s: %s", image_url, exc)
            return None

        if isinstance(record, dict):
            return self._extract_identifier(record)
        return None
