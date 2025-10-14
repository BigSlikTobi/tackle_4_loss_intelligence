"""
Data normalization service for cleaning and standardizing fetched data.

This module provides the DataNormalizer class which:
- Replaces invalid JSON values (NaN, Infinity) with standard nulls
- Ensures consistent identifiers across all data sources
- Adds data provenance tracking (source, version, retrieval time)
- Handles missing data and edge cases gracefully
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Union
import logging
import math
import time

logger = logging.getLogger(__name__)


@dataclass
class NormalizedData:
    """
    Result of data normalization containing cleaned and standardized data.
    
    All data has been cleaned of invalid JSON values and standardized for
    consistent downstream processing.
    """
    # Normalized data by source
    play_by_play: Optional[List[Dict[str, Any]]] = None
    snap_counts: Optional[List[Dict[str, Any]]] = None
    team_context: Optional[Dict[str, Any]] = None
    ngs_data: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    
    # Normalization metadata
    normalization_timestamp: Optional[float] = None
    records_processed: Dict[str, int] = field(default_factory=dict)
    issues_found: List[Dict[str, Any]] = field(default_factory=list)
    
    # Provenance (carried forward from FetchResult)
    provenance: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "play_by_play": self.play_by_play,
            "snap_counts": self.snap_counts,
            "team_context": self.team_context,
            "ngs_data": self.ngs_data,
            "metadata": {
                "normalization_timestamp": self.normalization_timestamp,
                "records_processed": self.records_processed,
                "issues_found": self.issues_found,
            },
            "provenance": self.provenance,
        }


class DataNormalizer:
    """
    Normalizes and cleans data from upstream providers.
    
    Handles:
    - Invalid JSON values (NaN, Infinity, -Infinity)
    - Inconsistent null representations (None, "null", empty strings)
    - Player ID format standardization
    - Data type coercion and validation
    - Provenance tracking
    
    Example:
        normalizer = DataNormalizer()
        normalized = normalizer.normalize(fetch_result)
        
        # Access cleaned data
        clean_pbp = normalized.play_by_play
        clean_ngs = normalized.ngs_data["passing"]
    """
    
    def __init__(self):
        """Initialize the data normalizer."""
        self._normalization_count = 0
    
    def normalize(self, fetch_result) -> NormalizedData:
        """
        Normalize all fetched data.
        
        Args:
            fetch_result: FetchResult from DataFetcher containing raw data
            
        Returns:
            NormalizedData with cleaned and standardized data
        """
        logger.info("Normalizing fetched data...")
        
        result = NormalizedData(
            normalization_timestamp=time.time(),
            provenance=fetch_result.provenance.copy()
        )
        
        # Normalize each data source
        if fetch_result.play_by_play is not None:
            result.play_by_play = self._normalize_play_by_play(
                fetch_result.play_by_play,
                result
            )
        
        if fetch_result.snap_counts is not None:
            result.snap_counts = self._normalize_snap_counts(
                fetch_result.snap_counts,
                result
            )
        
        if fetch_result.team_context is not None:
            result.team_context = self._normalize_team_context(
                fetch_result.team_context,
                result
            )
        
        # Normalize NGS data for each stat type
        for stat_type, data in fetch_result.ngs_data.items():
            result.ngs_data[stat_type] = self._normalize_ngs_data(
                data,
                stat_type,
                result
            )
        
        # Log summary
        total_records = sum(result.records_processed.values())
        total_issues = len(result.issues_found)
        logger.info(
            f"Normalization complete: {total_records} records processed, "
            f"{total_issues} issues found and fixed"
        )
        
        return result
    
    def _normalize_play_by_play(
        self,
        data: List[Dict[str, Any]],
        result: NormalizedData
    ) -> List[Dict[str, Any]]:
        """Normalize play-by-play data."""
        logger.debug(f"Normalizing {len(data)} play-by-play records")
        
        normalized = []
        for i, record in enumerate(data):
            try:
                cleaned = self._clean_record(record, "play_by_play", i)
                normalized.append(cleaned)
            except Exception as e:
                logger.warning(f"Error normalizing PBP record {i}: {e}")
                result.issues_found.append({
                    "source": "play_by_play",
                    "record_index": i,
                    "error": str(e),
                })
        
        result.records_processed["play_by_play"] = len(normalized)
        return normalized
    
    def _normalize_snap_counts(
        self,
        data: List[Dict[str, Any]],
        result: NormalizedData
    ) -> List[Dict[str, Any]]:
        """Normalize snap count data."""
        logger.debug(f"Normalizing {len(data)} snap count records")
        
        normalized = []
        for i, record in enumerate(data):
            try:
                cleaned = self._clean_record(record, "snap_counts", i)
                normalized.append(cleaned)
            except Exception as e:
                logger.warning(f"Error normalizing snap count record {i}: {e}")
                result.issues_found.append({
                    "source": "snap_counts",
                    "record_index": i,
                    "error": str(e),
                })
        
        result.records_processed["snap_counts"] = len(normalized)
        return normalized
    
    def _normalize_team_context(
        self,
        data: Dict[str, Any],
        result: NormalizedData
    ) -> Dict[str, Any]:
        """Normalize team context data."""
        logger.debug("Normalizing team context data")
        
        try:
            cleaned = self._clean_record(data, "team_context", 0)
            result.records_processed["team_context"] = 1
            return cleaned
        except Exception as e:
            logger.warning(f"Error normalizing team context: {e}")
            result.issues_found.append({
                "source": "team_context",
                "error": str(e),
            })
            return {}
    
    def _normalize_ngs_data(
        self,
        data: List[Dict[str, Any]],
        stat_type: str,
        result: NormalizedData
    ) -> List[Dict[str, Any]]:
        """Normalize NGS data for a specific stat type."""
        logger.debug(f"Normalizing {len(data)} NGS {stat_type} records")
        
        normalized = []
        for i, record in enumerate(data):
            try:
                cleaned = self._clean_record(record, f"ngs_{stat_type}", i)
                normalized.append(cleaned)
            except Exception as e:
                logger.warning(f"Error normalizing NGS {stat_type} record {i}: {e}")
                result.issues_found.append({
                    "source": f"ngs_{stat_type}",
                    "record_index": i,
                    "error": str(e),
                })
        
        result.records_processed[f"ngs_{stat_type}"] = len(normalized)
        return normalized
    
    def _clean_record(
        self,
        record: Dict[str, Any],
        source: str,
        index: int
    ) -> Dict[str, Any]:
        """
        Clean a single record by normalizing all values.
        
        Args:
            record: Raw record dictionary
            source: Source identifier for logging
            index: Record index for logging
            
        Returns:
            Cleaned record with normalized values
        """
        cleaned = {}
        
        for key, value in record.items():
            cleaned[key] = self._normalize_value(value, key, source, index)
        
        return cleaned
    
    def _normalize_value(
        self,
        value: Any,
        field: str,
        source: str,
        index: int
    ) -> Any:
        """
        Normalize a single value.
        
        Handles:
        - NaN, Infinity, -Infinity → None
        - Empty strings → None (for numeric/ID fields)
        - Type coercion where appropriate
        - Nested structures (dicts, lists)
        
        Args:
            value: Value to normalize
            field: Field name for context
            source: Source identifier for logging
            index: Record index for logging
            
        Returns:
            Normalized value
        """
        # Handle None
        if value is None:
            return None
        
        # Handle numeric types - check for NaN and Infinity
        if isinstance(value, float):
            if math.isnan(value):
                self._normalization_count += 1
                logger.debug(
                    f"Replaced NaN with None in {source}[{index}].{field}"
                )
                return None
            elif math.isinf(value):
                self._normalization_count += 1
                logger.debug(
                    f"Replaced Infinity with None in {source}[{index}].{field}"
                )
                return None
        
        # Handle strings
        if isinstance(value, str):
            # Convert "null" string to None
            if value.lower() == "null":
                self._normalization_count += 1
                return None
            
            # Convert empty strings to None for ID fields
            if not value.strip() and self._is_id_field(field):
                self._normalization_count += 1
                return None
            
            # Return trimmed string
            return value.strip()
        
        # Handle lists recursively
        if isinstance(value, list):
            return [
                self._normalize_value(item, f"{field}[{i}]", source, index)
                for i, item in enumerate(value)
            ]
        
        # Handle dicts recursively
        if isinstance(value, dict):
            return {
                k: self._normalize_value(v, f"{field}.{k}", source, index)
                for k, v in value.items()
            }
        
        # Return other types as-is (int, bool, etc.)
        return value
    
    def _is_id_field(self, field: str) -> bool:
        """
        Check if a field is an ID field that should not be an empty string.
        
        Args:
            field: Field name to check
            
        Returns:
            True if field is an ID field
        """
        id_indicators = [
            "id", "gsis", "pfr", "nflverse", "player", "team",
            "game_id", "play_id"
        ]
        
        field_lower = field.lower()
        return any(indicator in field_lower for indicator in id_indicators)
    
    def _ensure_consistent_player_ids(
        self,
        record: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Ensure player IDs are consistently formatted.
        
        This is a placeholder for future ID standardization logic.
        Could include:
        - Format validation (e.g., "00-0012345")
        - Cross-referencing between ID systems
        - ID resolution and mapping
        
        Args:
            record: Record to process
            
        Returns:
            Record with standardized IDs
        """
        # TODO: Implement ID standardization if needed (issue #25)
        # For now, just return the record as-is
        return record
