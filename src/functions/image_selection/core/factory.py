"""Factories for constructing image selection request models."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .config import ImageSelectionRequest, LLMConfig, SearchConfig, SupabaseConfig, VisionConfig


def request_from_payload(payload: Dict[str, Any]) -> ImageSelectionRequest:
    """Build an ImageSelectionRequest from an API-style payload."""

    article_text = payload.get("article_text")
    explicit_query = payload.get("query")
    source_url = payload.get("source_url")
    required_terms = payload.get("required_terms")
    num_images = int(payload.get("num_images", 1))

    enable_llm = payload.get("enable_llm", True)
    llm_payload: Optional[Dict[str, Any]] = payload.get("llm")
    llm_config: Optional[LLMConfig] = None
    if enable_llm:
        if not isinstance(llm_payload, dict):
            raise ValueError("llm configuration is required when enable_llm is true")
        llm_config = LLMConfig(
            provider=llm_payload.get("provider", "gemini"),
            model=llm_payload.get("model"),
            api_key=llm_payload.get("api_key"),
            parameters=llm_payload.get("parameters", {}),
            prompt_template=llm_payload.get("prompt_template"),
            max_query_words=int(llm_payload.get("max_query_words", 8)),
            enabled=True,
        )
        if not llm_config.model or not llm_config.api_key:
            raise ValueError("llm.model and llm.api_key are required")

    search_payload = payload.get("search")
    search_config: Optional[SearchConfig] = None
    if search_payload is None:
        search_config = None
    elif not isinstance(search_payload, dict):
        raise ValueError("search configuration must be an object when provided")
    else:
        api_key = search_payload.get("api_key")
        engine_id = search_payload.get("engine_id")
        if api_key and engine_id:
            search_config = SearchConfig(
                api_key=api_key,
                engine_id=engine_id,
                max_candidates=int(search_payload.get("max_candidates", 10)),
                safe_search=search_payload.get("safe", "active"),
                rights_filter=search_payload.get(
                    "rights", "cc_publicdomain,cc_attribute,cc_sharealike"
                ),
                image_type=search_payload.get("image_type", "photo"),
                image_size=search_payload.get("image_size", "large"),
            )
        elif api_key or engine_id:
            raise ValueError(
                "Both search.api_key and search.engine_id are required when using Google Custom Search"
            )

    supabase_payload = payload.get("supabase")
    supabase_config: Optional[SupabaseConfig] = None
    if supabase_payload is None:
        supabase_config = None
    elif not isinstance(supabase_payload, dict):
        raise ValueError("supabase configuration must be an object when provided")
    elif supabase_payload.get("enabled") is False:
        supabase_config = None
    else:
        url = supabase_payload.get("url")
        key = supabase_payload.get("key")
        if url and key:
            supabase_config = SupabaseConfig(
                url=url,
                key=key,
                bucket=supabase_payload.get("bucket", "images"),
                table=supabase_payload.get("table", "article_images"),
                schema=supabase_payload.get("schema", "content"),
            )
        elif url or key:
            raise ValueError(
                "Both supabase.url and supabase.key are required when enabling Supabase persistence"
            )

    # Parse vision validation configuration
    vision_payload = payload.get("vision")
    vision_config: Optional[VisionConfig] = None
    
    # Detect Cloud Functions environment to disable CLIP by default (avoids cold start delays)
    is_cloud_function = bool(
        os.getenv("FUNCTION_NAME") or  # GCF Gen1
        os.getenv("K_SERVICE") or       # GCF Gen2 / Cloud Run
        os.getenv("AWS_LAMBDA_FUNCTION_NAME")  # AWS Lambda
    )
    default_enable_clip = not is_cloud_function  # Disable CLIP in cloud, enable locally
    default_strict_mode = is_cloud_function
    default_min_relevance = 7.0 if default_strict_mode else 0.0
    default_min_source_score = 0.5 if default_strict_mode else 0.0
    
    if vision_payload is None:
        # Default: vision validation enabled, CLIP based on environment
        vision_config = VisionConfig(enable_clip=default_enable_clip)
    elif not isinstance(vision_payload, dict):
        raise ValueError("vision configuration must be an object when provided")
    elif vision_payload.get("enabled") is False:
        vision_config = None
    else:
        # Explicit config: use provided values, or fall back to environment-aware defaults
        vision_config = VisionConfig(
            enabled=vision_payload.get("enabled", True),
            google_cloud_credentials=vision_payload.get("google_cloud_credentials"),
            clip_model=vision_payload.get("clip_model", "openai/clip-vit-base-patch32"),
            text_rejection_threshold=int(
                vision_payload.get("text_rejection_threshold", 15)
            ),
            similarity_threshold=float(
                vision_payload.get("similarity_threshold", 0.25)
            ),
            enable_ocr=vision_payload.get("enable_ocr", True),
            enable_clip=vision_payload.get("enable_clip", default_enable_clip),
        )

    request_model = ImageSelectionRequest(
        article_text=article_text,
        explicit_query=explicit_query,
        source_url=source_url,
        required_terms=_normalize_terms(required_terms),
        num_images=num_images,
        enable_llm=enable_llm,
        strict_mode=bool(payload.get("strict_mode", default_strict_mode)),
        min_relevance_score=float(payload.get("min_relevance_score", default_min_relevance)),
        min_source_score=float(payload.get("min_source_score", default_min_source_score)),
        min_width=int(payload.get("min_width", 1024)),
        min_height=int(payload.get("min_height", 576)),
        min_bytes=int(payload.get("min_bytes", 50_000)),
        llm_config=llm_config,
        search_config=search_config,
        supabase_config=supabase_config,
        vision_config=vision_config,
    )
    request_model.validate()
    return request_model


def _normalize_terms(raw_terms: Any) -> Optional[list[str]]:
    if raw_terms is None:
        return None
    if isinstance(raw_terms, str):
        terms = [term.strip() for term in raw_terms.split(",")]
    elif isinstance(raw_terms, list):
        terms = [str(term).strip() for term in raw_terms]
    else:
        raise ValueError("required_terms must be a list or comma-separated string")
    cleaned = [term for term in terms if len(term) >= 3]
    return cleaned or None
