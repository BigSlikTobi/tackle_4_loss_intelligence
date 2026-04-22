"""Reader + writer for the ``news_url_content_ephemeral`` handoff table.

The table is the bus between the extractor (writes) and downstream
consumers (reads + marks consumed). Schema lives in ``../schema.sql``.

Both classes use the same Supabase client conventions as ``FactsReader`` /
``FactsWriter`` — paginated reads, chunked writes, no module-globals.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

TABLE_NAME = "news_url_content_ephemeral"

_DEFAULT_CHUNK_SIZE = 100
_DEFAULT_PAGE_SIZE = 1000
_DEFAULT_TTL_HOURS = 48


class EphemeralContentWriter:
    """Write-side helper for the ephemeral content table."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def upsert_content(
        self,
        rows: Sequence[Dict[str, Any]],
        *,
        ttl_hours: Optional[int] = None,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        now: Optional[datetime] = None,
    ) -> int:
        """UPSERT one row per ``news_url_id``.

        Each row must include ``news_url_id`` and ``content``; other columns
        (``title``, ``paragraphs``, ``metadata``) are optional. ``expires_at``
        is set here (overriding any default) so callers can pass a custom TTL
        without round-tripping through the DB default.

        Returns the number of rows successfully written.
        """
        if not rows:
            return 0

        ttl = ttl_hours if ttl_hours and ttl_hours > 0 else _DEFAULT_TTL_HOURS
        base_now = now or datetime.now(timezone.utc)
        expires_iso = (base_now + timedelta(hours=ttl)).isoformat()
        extracted_iso = base_now.isoformat()

        prepared: List[Dict[str, Any]] = []
        for row in rows:
            if not row.get("news_url_id") or row.get("content") is None:
                logger.warning(
                    "Skipping ephemeral row with missing news_url_id/content: %s",
                    {k: row.get(k) for k in ("news_url_id",)},
                )
                continue
            prepared.append(
                {
                    "news_url_id": row["news_url_id"],
                    "content": row["content"],
                    "title": row.get("title"),
                    "paragraphs": row.get("paragraphs"),
                    "metadata": row.get("metadata"),
                    "extracted_at": extracted_iso,
                    "consumed_at": None,
                    "expires_at": expires_iso,
                }
            )

        if not prepared:
            return 0

        written = 0
        for i in range(0, len(prepared), chunk_size):
            chunk = prepared[i : i + chunk_size]
            try:
                response = (
                    self.client.table(TABLE_NAME)
                    .upsert(chunk, on_conflict="news_url_id")
                    .execute()
                )
                written += len(getattr(response, "data", []) or [])
            except Exception as exc:
                logger.error(
                    "Failed to upsert ephemeral content chunk (size=%d): %s",
                    len(chunk),
                    exc,
                )
        return written

    def upsert_one(
        self,
        row: Dict[str, Any],
        *,
        ttl_hours: Optional[int] = None,
    ) -> bool:
        """Single-row convenience over :meth:`upsert_content`."""
        return self.upsert_content([row], ttl_hours=ttl_hours) > 0

    def mark_consumed(
        self,
        news_url_ids: Sequence[str],
        *,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        now: Optional[datetime] = None,
    ) -> int:
        """Stamp ``consumed_at`` for the supplied IDs. Returns rows updated."""
        ids = [i for i in news_url_ids if i]
        if not ids:
            return 0
        now_iso = (now or datetime.now(timezone.utc)).isoformat()
        updated = 0
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            try:
                response = (
                    self.client.table(TABLE_NAME)
                    .update({"consumed_at": now_iso})
                    .in_("news_url_id", chunk)
                    .is_("consumed_at", "null")
                    .execute()
                )
                updated += len(getattr(response, "data", []) or [])
            except Exception as exc:
                logger.error(
                    "Failed to mark consumed for ephemeral chunk (size=%d): %s",
                    len(chunk),
                    exc,
                )
        return updated

    def delete_expired_and_consumed(
        self,
        *,
        batch_size: int = 500,
        max_batches: Optional[int] = None,
        now: Optional[datetime] = None,
        dry_run: bool = False,
    ) -> int:
        """Delete rows where ``consumed_at IS NOT NULL OR expires_at < now()``.

        Performed in batches: select IDs (paginated), then delete by IN.
        Returns the number of rows deleted (or counted, in dry-run).
        """
        now_iso = (now or datetime.now(timezone.utc)).isoformat()
        total = 0
        batches = 0
        while True:
            try:
                response = (
                    self.client.table(TABLE_NAME)
                    .select("id")
                    .or_(f"consumed_at.not.is.null,expires_at.lt.{now_iso}")
                    .limit(batch_size)
                    .execute()
                )
            except Exception as exc:
                logger.error("Failed to query ephemeral rows for sweep: %s", exc)
                break

            rows = getattr(response, "data", []) or []
            if not rows:
                break
            ids = [r["id"] for r in rows if r.get("id")]
            if not ids:
                break

            if dry_run:
                total += len(ids)
            else:
                try:
                    self.client.table(TABLE_NAME).delete().in_("id", ids).execute()
                    total += len(ids)
                except Exception as exc:
                    logger.error(
                        "Failed to delete ephemeral sweep batch (size=%d): %s",
                        len(ids),
                        exc,
                    )
                    break

            batches += 1
            if max_batches is not None and batches >= max_batches:
                break
            if len(rows) < batch_size:
                break
        return total


class EphemeralContentReader:
    """Read-side helper for the ephemeral content table."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def fetch_content(self, news_url_id: str) -> Optional[str]:
        """Return the joined content for ``news_url_id`` if a fresh row exists."""
        if not news_url_id:
            return None
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            response = (
                self.client.table(TABLE_NAME)
                .select("content")
                .eq("news_url_id", news_url_id)
                .is_("consumed_at", "null")
                .gt("expires_at", now_iso)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            logger.warning("Ephemeral fetch failed for %s: %s", news_url_id, exc)
            return None
        rows = getattr(response, "data", []) or []
        if not rows:
            return None
        content = rows[0].get("content")
        return content if isinstance(content, str) and content else None

    def fetch_content_bulk(
        self,
        news_url_ids: Sequence[str],
        *,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        page_size: int = _DEFAULT_PAGE_SIZE,
    ) -> Dict[str, str]:
        """Return ``{news_url_id: content}`` for fresh, unexpired rows."""
        ids = [i for i in news_url_ids if i]
        if not ids:
            return {}
        now_iso = datetime.now(timezone.utc).isoformat()
        out: Dict[str, str] = {}
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            offset = 0
            while True:
                try:
                    response = (
                        self.client.table(TABLE_NAME)
                        .select("news_url_id,content")
                        .in_("news_url_id", chunk)
                        .is_("consumed_at", "null")
                        .gt("expires_at", now_iso)
                        .range(offset, offset + page_size - 1)
                        .execute()
                    )
                except Exception as exc:
                    logger.warning(
                        "Ephemeral bulk fetch failed (chunk size=%d): %s",
                        len(chunk),
                        exc,
                    )
                    break
                rows = getattr(response, "data", []) or []
                for row in rows:
                    nid = row.get("news_url_id")
                    content = row.get("content")
                    if nid and isinstance(content, str) and content:
                        out[nid] = content
                if len(rows) < page_size:
                    break
                offset += page_size
        return out

    def fetch_unconsumed_ids(
        self,
        *,
        limit: int = 1000,
    ) -> List[str]:
        """Return up to ``limit`` ``news_url_id`` values for unconsumed, unexpired rows."""
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            response = (
                self.client.table(TABLE_NAME)
                .select("news_url_id")
                .is_("consumed_at", "null")
                .gt("expires_at", now_iso)
                .order("extracted_at", desc=False)
                .limit(limit)
                .execute()
            )
        except Exception as exc:
            logger.warning("Failed to list unconsumed ephemeral rows: %s", exc)
            return []
        rows = getattr(response, "data", []) or []
        return [r["news_url_id"] for r in rows if r.get("news_url_id")]
