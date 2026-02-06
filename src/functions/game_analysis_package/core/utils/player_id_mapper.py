"""Player ID mapping and normalization utilities."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Set

from src.shared.db import get_supabase_client

logger = logging.getLogger(__name__)


@dataclass
class PlayerIdMappingConfig:
    """Configuration for player ID mapping."""

    enabled: bool = True
    primary_system: str = "gsis"
    cache_ttl_seconds: int = 3600
    roster_fallback_enabled: bool = True
    supabase_in_batch_size: int = 150

    @classmethod
    def from_env(cls) -> "PlayerIdMappingConfig":
        enabled_raw = os.getenv("PLAYER_ID_STANDARDIZATION_ENABLED", "true").strip().lower()
        enabled = enabled_raw not in {"0", "false", "no", "off"}
        primary_system = os.getenv("PLAYER_ID_PRIMARY_SYSTEM", "gsis").strip().lower()
        cache_ttl = os.getenv("PLAYER_ID_MAPPING_CACHE_TTL", "3600").strip()
        roster_fallback_raw = os.getenv("PLAYER_ID_ROSTER_FALLBACK_ENABLED", "true").strip().lower()
        roster_fallback_enabled = roster_fallback_raw not in {"0", "false", "no", "off"}
        supabase_batch_raw = os.getenv("PLAYER_ID_SUPABASE_IN_BATCH_SIZE", "150").strip()
        try:
            cache_ttl_seconds = int(cache_ttl)
        except ValueError:
            cache_ttl_seconds = 3600
        try:
            supabase_in_batch_size = int(supabase_batch_raw)
        except ValueError:
            supabase_in_batch_size = 150
        return cls(
            enabled=enabled,
            primary_system=primary_system,
            cache_ttl_seconds=cache_ttl_seconds,
            roster_fallback_enabled=roster_fallback_enabled,
            supabase_in_batch_size=supabase_in_batch_size,
        )


class PlayerIdMapper:
    """Resolve player IDs across systems (GSIS/PFR), with layered backends.

    Resolution order:
    - Injected mappings (tests / offline)
    - Supabase `players(pfr_id -> player_id)` if configured
    - `nflreadpy.load_rosters(season)` fallback (optional, requires season)
    """

    _GSIS_RE = re.compile(r"^\d{2}-\d{7}$")
    # Typical PFR ids look like "MahoPa00" but upstream sources sometimes vary in casing
    # and (occasionally) the letter segment length.
    _PFR_RE = re.compile(r"^[A-Za-z]{4,10}\d{2}$")

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
        self.roster_fallback_enabled = self.config.roster_fallback_enabled
        self.supabase_in_batch_size = max(1, self.config.supabase_in_batch_size)
        self._client = supabase_client
        self._pfr_to_gsis: Dict[str, str] = {}
        self._pfr_negative_cache: Dict[str, float] = {}
        self._roster_cache: Dict[int, Dict[str, str]] = {}
        self._static_mapping_only = False

        if pfr_to_gsis:
            for key, value in pfr_to_gsis.items():
                if key:
                    self._pfr_to_gsis[key.lower()] = value
            self._static_mapping_only = True

        if self.enabled and self._client is None:
            try:
                self._client = get_supabase_client()
            except Exception as exc:
                # Keep the mapper enabled if we have an offline backend to fall back to.
                self._client = None
                if self._static_mapping_only or self.roster_fallback_enabled:
                    logger.info(
                        "Supabase unavailable; player ID mapping will run without Supabase: %s",
                        exc,
                    )
                else:
                    self.enabled = False
                    logger.warning(
                        "Player ID standardization disabled (Supabase unavailable): %s",
                        exc,
                    )

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

    @staticmethod
    def _chunks(values: List[str], size: int) -> Iterable[List[str]]:
        for i in range(0, len(values), size):
            yield values[i:i + size]

    @staticmethod
    def _convert_generic_to_records(raw_data: Any) -> List[Dict[str, Any]]:
        """Convert nflreadpy structures (Polars/Pandas/list) into dict records."""
        if raw_data is None:
            return []

        try:
            import polars as pl  # type: ignore
            if isinstance(raw_data, pl.DataFrame):  # pragma: no branch - depends on env
                return [
                    dict(zip(raw_data.columns, row))
                    for row in raw_data.iter_rows()
                ]
        except ImportError:  # pragma: no cover - polars optional
            pass

        if hasattr(raw_data, "to_pandas"):
            df = raw_data.to_pandas()
            return df.to_dict(orient="records")  # type: ignore[no-any-return]

        try:
            import pandas as pd  # type: ignore
            if isinstance(raw_data, pd.DataFrame):
                return raw_data.to_dict(orient="records")
        except ImportError:  # pragma: no cover - pandas optional
            pass

        if isinstance(raw_data, list):
            return [dict(item) for item in raw_data if isinstance(item, dict)]

        if isinstance(raw_data, dict):
            return [dict(raw_data)]

        raise TypeError(f"Unsupported data type: {type(raw_data)}")

    def _load_roster_mapping(self, season: int) -> Dict[str, str]:
        if season in self._roster_cache:
            return self._roster_cache[season]

        if not self.roster_fallback_enabled:
            self._roster_cache[season] = {}
            return self._roster_cache[season]

        try:
            from nflreadpy import load_rosters  # Lazy import
        except ImportError:
            logger.debug("nflreadpy not installed; roster fallback disabled for season=%s", season)
            self._roster_cache[season] = {}
            return self._roster_cache[season]

        raw_data = load_rosters([season])
        records = self._convert_generic_to_records(raw_data)
        mapping: Dict[str, str] = {}
        for record in records:
            pfr_value = self._clean_str(record.get("pfr_id") or record.get("pfr_player_id"))
            gsis_value = self._clean_str(record.get("gsis_id") or record.get("player_id"))
            if pfr_value and gsis_value:
                mapping[pfr_value.lower()] = gsis_value

        self._roster_cache[season] = mapping
        logger.debug("Loaded %d roster player ID mappings for season=%s", len(mapping), season)
        return mapping

    def prefetch_pfr_ids(self, pfr_ids: Iterable[str], *, season: Optional[int] = None) -> None:
        """Prefetch Supabase mappings for the given PFR ids (no full-table scans)."""
        if not self.enabled:
            return

        now = time.time()
        candidates: Dict[str, str] = {}
        for value in pfr_ids:
            text = self._clean_str(value)
            if not text:
                continue
            if len(text) < 4 or len(text) > 32:
                continue
            key = text.lower()
            candidates.setdefault(key, text)

        if not candidates:
            return

        # Optional cheap local enrichment from roster data if season is available.
        if season is not None and self.roster_fallback_enabled:
            roster_map = self._load_roster_mapping(season)
            for key in list(candidates.keys()):
                mapped = roster_map.get(key)
                if mapped:
                    self._pfr_to_gsis[key] = mapped
                    candidates.pop(key, None)

        if self._client is None:
            return

        to_query: Set[str] = set()
        for key, representative in candidates.items():
            if key in self._pfr_to_gsis:
                continue
            last_miss = self._pfr_negative_cache.get(key)
            if last_miss is not None and (now - last_miss) < self.cache_ttl_seconds:
                continue
            to_query.add(representative)

        if not to_query:
            return

        queried_keys: Set[str] = set()
        found_keys: Set[str] = set()

        for batch in self._chunks(sorted(to_query), self.supabase_in_batch_size):
            response = (
                self._client
                .table("players")
                .select("player_id,pfr_id")
                .in_("pfr_id", batch)
                .execute()
            )
            rows = getattr(response, "data", None) or []
            for row in rows:
                gsis_id = self._clean_str(row.get("player_id"))
                pfr_id = self._clean_str(row.get("pfr_id"))
                if not gsis_id or not pfr_id:
                    continue
                key = pfr_id.lower()
                self._pfr_to_gsis[key] = gsis_id
                found_keys.add(key)
            for value in batch:
                queried_keys.add(str(value).lower())

        for key in queried_keys:
            if key in found_keys:
                self._pfr_negative_cache.pop(key, None)
            else:
                self._pfr_negative_cache[key] = now

    def resolve_gsis_from_pfr(self, pfr_id: Optional[str], *, season: Optional[int] = None) -> Optional[str]:
        if not pfr_id or not self.enabled:
            return None

        cleaned = self._clean_str(pfr_id)
        if not cleaned:
            return None
        if len(cleaned) < 4 or len(cleaned) > 32:
            return None

        key = cleaned.lower()
        cached = self._pfr_to_gsis.get(key)
        if cached:
            return cached

        now = time.time()
        last_miss = self._pfr_negative_cache.get(key)
        if last_miss is not None and (now - last_miss) < self.cache_ttl_seconds:
            return None

        if self._client is not None:
            self.prefetch_pfr_ids([cleaned])
            cached = self._pfr_to_gsis.get(key)
            if cached:
                return cached

        if season is not None and self.roster_fallback_enabled:
            roster_map = self._load_roster_mapping(season)
            mapped = roster_map.get(key)
            if mapped:
                self._pfr_to_gsis[key] = mapped
                self._pfr_negative_cache.pop(key, None)
                return mapped

        self._pfr_negative_cache[key] = now
        return None

    def normalize_to_gsis(self, value: Optional[str], *, season: Optional[int] = None) -> Optional[str]:
        if not value:
            return None
        gsis_candidate = self.normalize_gsis_id(value)
        if gsis_candidate and self.is_valid_gsis_id(gsis_candidate):
            return gsis_candidate
        if isinstance(value, str):
            mapped = self.resolve_gsis_from_pfr(value, season=season)
            if mapped:
                return mapped
        return None

    def normalize_player_id_list(
        self,
        values: Optional[Iterable[str]],
        *,
        season: Optional[int] = None,
    ) -> Optional[List[str]]:
        if values is None:
            return None
        if not isinstance(values, list):
            return values  # type: ignore[return-value]
        normalized: List[str] = []
        for value in values:
            mapped = self.normalize_to_gsis(value, season=season)
            normalized.append(mapped or value)
        return normalized
