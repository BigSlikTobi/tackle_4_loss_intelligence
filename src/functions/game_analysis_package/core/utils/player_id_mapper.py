"""Player ID mapping and normalization utilities."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import re
import time
from typing import Dict, Iterable, List, Optional

from src.shared.db import get_supabase_client

logger = logging.getLogger(__name__)


@dataclass
class PlayerIdMappingConfig:
    """Configuration for player ID mapping."""

    enabled: bool = True
    primary_system: str = "gsis"
    cache_ttl_seconds: int = 3600

    @classmethod
    def from_env(cls) -> "PlayerIdMappingConfig":
        enabled_raw = os.getenv("PLAYER_ID_STANDARDIZATION_ENABLED", "true").strip().lower()
        enabled = enabled_raw not in {"0", "false", "no", "off"}
        primary_system = os.getenv("PLAYER_ID_PRIMARY_SYSTEM", "gsis").strip().lower()
        cache_ttl = os.getenv("PLAYER_ID_MAPPING_CACHE_TTL", "3600").strip()
        try:
            cache_ttl_seconds = int(cache_ttl)
        except ValueError:
            cache_ttl_seconds = 3600
        return cls(
            enabled=enabled,
            primary_system=primary_system,
            cache_ttl_seconds=cache_ttl_seconds,
        )


class PlayerIdMapper:
    """Resolve player IDs across GSIS/PFR systems using Supabase mappings."""

    _GSIS_RE = re.compile(r"^\d{2}-\d{7}$")
    _PFR_RE = re.compile(r"^[A-Z][a-z]{2,4}[A-Z][a-z]\d{2}$")

    def __init__(
        self,
        config: Optional[PlayerIdMappingConfig] = None,
        supabase_client=None,
        pfr_to_gsis: Optional[Dict[str, str]] = None,
    ) -> None:
        self.config = config or PlayerIdMappingConfig.from_env()
        self.enabled = self.config.enabled
        self.primary_system = self.config.primary_system
        self.cache_ttl_seconds = self.config.cache_ttl_seconds
        self._client = supabase_client
        self._pfr_to_gsis: Dict[str, str] = {}
        self._last_loaded_at: float = 0.0
        self._mappings_loaded = False

        if pfr_to_gsis:
            self._pfr_to_gsis.update(pfr_to_gsis)
            for key, value in pfr_to_gsis.items():
                if key:
                    self._pfr_to_gsis[key.lower()] = value
            self._mappings_loaded = True

        if self.enabled and self._client is None:
            try:
                self._client = get_supabase_client()
            except Exception as exc:
                self.enabled = False
                logger.warning(
                    "Player ID standardization disabled (Supabase unavailable): %s",
                    exc,
                )

    def _load_mappings_if_needed(self) -> None:
        if not self.enabled or self._client is None:
            return
        now = time.time()
        if self._mappings_loaded and (now - self._last_loaded_at) < self.cache_ttl_seconds:
            return

        page_size = 1000
        offset = 0
        total = 0
        mapping: Dict[str, str] = {}

        while True:
            response = (
                self._client
                .table("players")
                .select("player_id,pfr_id")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            rows = response.data or []
            for row in rows:
                gsis_id = self._clean_str(row.get("player_id"))
                pfr_id = self._clean_str(row.get("pfr_id"))
                if gsis_id and pfr_id:
                    mapping[pfr_id] = gsis_id
                    mapping[pfr_id.lower()] = gsis_id
            total += len(rows)
            if len(rows) < page_size:
                break
            offset += page_size

        self._pfr_to_gsis = mapping
        self._mappings_loaded = True
        self._last_loaded_at = now
        logger.info("Loaded %d player ID mappings from Supabase", total)

    @staticmethod
    def _clean_str(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def is_valid_gsis_id(self, value: Optional[str]) -> bool:
        if not value:
            return False
        return bool(self._GSIS_RE.match(value))

    def is_valid_pfr_id(self, value: Optional[str]) -> bool:
        if not value:
            return False
        return bool(self._PFR_RE.match(value))

    def normalize_gsis_id(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        cleaned = self._clean_str(value)
        if not cleaned:
            return None
        if self.is_valid_gsis_id(cleaned):
            return cleaned
        if cleaned.startswith("00") and len(cleaned) == 9 and cleaned[2:].isdigit():
            return f"00-{cleaned[2:]}"
        digits = "".join(ch for ch in cleaned if ch.isdigit())
        if len(digits) == 7:
            return f"00-{digits}"
        if len(digits) == 8:
            return f"00-{digits[-7:]}"
        return cleaned

    def resolve_gsis_from_pfr(self, pfr_id: Optional[str]) -> Optional[str]:
        if not pfr_id:
            return None
        self._load_mappings_if_needed()
        if not self._pfr_to_gsis:
            return None
        cleaned = self._clean_str(pfr_id)
        if not cleaned:
            return None
        return self._pfr_to_gsis.get(cleaned) or self._pfr_to_gsis.get(cleaned.lower())

    def normalize_to_gsis(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        gsis_candidate = self.normalize_gsis_id(value)
        if gsis_candidate and self.is_valid_gsis_id(gsis_candidate):
            return gsis_candidate
        if self.is_valid_pfr_id(value):
            mapped = self.resolve_gsis_from_pfr(value)
            if mapped:
                return mapped
        return None

    def normalize_player_id_list(self, values: Optional[Iterable[str]]) -> Optional[List[str]]:
        if values is None:
            return None
        if not isinstance(values, list):
            return values  # type: ignore[return-value]
        normalized: List[str] = []
        for value in values:
            mapped = self.normalize_to_gsis(value)
            normalized.append(mapped or value)
        return normalized
