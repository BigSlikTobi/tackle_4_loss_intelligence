"""Supabase integration helpers for the daily team update pipeline."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import httpx

from src.shared.db.connection import SupabaseConfig as SharedSupabaseConfig
from src.shared.db.connection import get_supabase_client

from ..contracts.config import SupabaseSettings

logger = logging.getLogger(__name__)


class SupabaseClient:
    """Thin wrapper around the Supabase Python SDK with HTTP function helpers."""

    def __init__(
        self,
        settings: SupabaseSettings,
        *,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.settings = settings
        self._client = None
        headers = {
            "apikey": settings.key,
            "Authorization": f"Bearer {settings.key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(settings.function_timeout, connect=5.0)
        self._http = http_client or httpx.Client(
            base_url=f"{settings.url}/functions/v1",
            headers=headers,
            timeout=timeout,
        )

    @property
    def client(self):
        """Return the underlying Supabase client, creating it on demand."""

        if self._client is None:
            config = SharedSupabaseConfig(
                url=str(self.settings.url),
                key=self.settings.key,
                schema=self.settings.schema,
            )
            self._client = get_supabase_client(config)
        return self._client

    def fetch_teams(self) -> List[Dict[str, Any]]:
        """Return metadata for all active teams."""

        response = (
            self.client.table(self.settings.team_table)
            .select("*")
            .execute()
        )
        data = getattr(response, "data", None) or []
        active: List[Dict[str, Any]] = []
        for record in data:
            if record is None:
                continue
            if record.get("is_active") is False or record.get("active") is False:
                continue
            active.append(record)
        return active

    def fetch_team_news_urls(self, team_abbr: str) -> List[Dict[str, Any]]:
        """Invoke the configured Edge Function to fetch news URLs for a team."""

        logger.debug("Fetching news URLs for team %s", team_abbr)
        try:
            response = self._http.get(
                f"/{self.settings.news_function}",
                params={"team_abbr": team_abbr},
            )
        except httpx.HTTPError as exc:  # pragma: no cover - network runtime
            msg = f"Failed to invoke {self.settings.news_function}: {exc}"
            logger.error(msg)
            raise RuntimeError(msg) from exc

        if response.status_code >= 400:
            logger.warning(
                "%s returned status %s for %s: %s",
                self.settings.news_function,
                response.status_code,
                team_abbr,
                response.text,
            )
            raise RuntimeError(
                f"team-news-urls returned {response.status_code}: {response.text}"
            )

        payload = response.json()
        urls = payload.get("urls") or payload.get("data") or []
        normalised: List[Dict[str, Any]] = []
        for item in urls:
            if isinstance(item, str):
                normalised.append({"url": item})
                continue
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("link")
            if not url:
                continue
            normalised.append(
                {
                    "url": url,
                    "source": item.get("source"),
                    "published_at": item.get("published_at") or item.get("publishedAt"),
                    "title": item.get("title"),
                }
            )
        return normalised

    def upsert_article(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Insert or update a team article record and return the stored row."""

        article_table = self.client.table(self.settings.article_table)
        conflict_fields = self.settings.article_on_conflict
        if conflict_fields:
            response = article_table.upsert(payload, on_conflict=conflict_fields).execute()
        else:
            response = article_table.upsert(payload).execute()
        data = getattr(response, "data", None) or []
        if not data:
            logger.warning("Supabase upsert returned no data for payload with team %s", payload.get("team"))
            return payload
        return data[0]

    def record_image(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Insert an image record and return its identifier."""

        table = self.client.table(self.settings.image_table)
        response = table.upsert(payload).execute()
        data = getattr(response, "data", None) or []
        if data:
            return data[0]

        lookup = (
            table.select("id,image_url,original_url,author,source")
            .eq("image_url", payload.get("image_url"))
            .limit(1)
            .execute()
        )
        lookup_data = getattr(lookup, "data", None) or []
        if lookup_data:
            return lookup_data[0]
        return payload

    def link_article_images(
        self,
        english_article_id: str,
        translated_article_id: Optional[str],
        image_ids: Iterable[str],
    ) -> None:
        """Create relationship row linking articles to images."""

        identifiers = [str(value) for value in image_ids if value]
        if not identifiers:
            logger.debug("No image identifiers provided for article %s", english_article_id)
            return

        table = self.client.table(self.settings.relationship_table)
        relationship_payload: Dict[str, Any] = {
            "team_article_id_en": english_article_id,
        }
        if translated_article_id:
            relationship_payload["team_article_id_de"] = translated_article_id

        image_columns = ("image_id_1", "image_id_2")
        for column_name, identifier in zip(image_columns, identifiers):
            relationship_payload[column_name] = identifier

        if len(identifiers) > len(image_columns):
            logger.info(
                "Supabase relationship table supports %s images; %s additional identifiers dropped for article %s",
                len(image_columns),
                len(identifiers) - len(image_columns),
                english_article_id,
            )

        existing = (
            table.select("id")
            .eq("team_article_id_en", english_article_id)
            .limit(1)
            .execute()
        )
        existing_rows = getattr(existing, "data", None) or []
        if existing_rows:
            row_id = existing_rows[0].get("id")
            update_payload = relationship_payload.copy()
            update_payload.pop("team_article_id_en", None)
            if row_id is not None:
                table.update(update_payload).eq("id", row_id).execute()
                return

        now = datetime.now(timezone.utc).isoformat()
        relationship_payload["created_at"] = now
        table.insert(relationship_payload).execute()

    def close(self) -> None:
        """Close underlying HTTP resources."""

        self._http.close()

    def __enter__(self) -> "SupabaseClient":  # pragma: no cover - convenience
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - convenience
        self.close()
