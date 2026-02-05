"""Configuration models for the image selection service."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """Configuration for the LLM that optimizes search queries."""

    provider: str
    model: str
    api_key: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    prompt_template: Optional[str] = None
    max_query_words: int = 8
    enabled: bool = True


@dataclass
class SearchConfig:
    """Configuration for primary image search provider."""

    api_key: str
    engine_id: str
    max_candidates: int = 10
    safe_search: str = "active"
    rights_filter: str = "cc_publicdomain,cc_attribute,cc_sharealike"
    image_type: str = "photo"
    image_size: str = "large"


@dataclass
class SupabaseConfig:
    """Configuration for Supabase storage and persistence."""

    url: str
    key: str
    bucket: str = "images"
    table: str = "article_images"
    schema: str = "content"


@dataclass
class VisionConfig:
    """Configuration for vision-based image validation (OCR + CLIP)."""

    enabled: bool = True
    google_cloud_credentials: Optional[str] = None  # JSON key string or file path
    clip_model: str = "openai/clip-vit-base-patch32"
    text_rejection_threshold: int = 15  # Max characters allowed before rejection
    similarity_threshold: float = 0.25  # Min CLIP similarity score (0.0-1.0)
    enable_ocr: bool = True
    enable_clip: bool = True


@dataclass
class ImageSelectionRequest:
    """Incoming request payload for image selection."""

    article_text: Optional[str] = None
    explicit_query: Optional[str] = None
    source_url: Optional[str] = None
    required_terms: Optional[List[str]] = None
    num_images: int = 1
    enable_llm: bool = True
    strict_mode: bool = False
    min_relevance_score: float = 7.0
    min_source_score: float = 0.5
    min_width: int = 1024
    min_height: int = 576
    min_bytes: int = 50_000
    llm_config: Optional[LLMConfig] = None
    search_config: Optional[SearchConfig] = None
    supabase_config: Optional[SupabaseConfig] = None
    vision_config: Optional[VisionConfig] = None

    def validate(self) -> None:
        """Validate the request and raise ValueError on problems."""

        if not (self.article_text or self.explicit_query):
            raise ValueError("Provide article_text or explicit_query to build a search query")

        if self.num_images < 1:
            raise ValueError("num_images must be at least 1")

        if self.enable_llm and not self.llm_config:
            raise ValueError("llm configuration is required when enable_llm is true")

        if self.search_config:
            if not self.search_config.api_key or not self.search_config.engine_id:
                raise ValueError(
                    "search.api_key and search.engine_id are required when search configuration is provided"
                )
        else:
            logger.info(
                "Google Custom Search credentials missing; service will rely on DuckDuckGo fallback only."
            )

        if self.supabase_config:
            if not self.supabase_config.url or not self.supabase_config.key:
                raise ValueError("supabase.url and supabase.key are required when Supabase is enabled")
        else:
            logger.info(
                "Supabase configuration missing; results will not be uploaded or persisted."
            )

        if self.min_relevance_score < 0:
            raise ValueError("min_relevance_score must be >= 0")
        if self.min_source_score < 0:
            raise ValueError("min_source_score must be >= 0")
        if self.min_width < 0 or self.min_height < 0:
            raise ValueError("min_width and min_height must be >= 0")
        if self.min_bytes < 0:
            raise ValueError("min_bytes must be >= 0")
