"""Factories for constructing image selection request models."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .config import ImageSelectionRequest, LLMConfig, SearchConfig, SupabaseConfig


def request_from_payload(payload: Dict[str, Any]) -> ImageSelectionRequest:
    """Build an ImageSelectionRequest from an API-style payload."""

    article_text = payload.get("article_text")
    explicit_query = payload.get("query")
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

    request_model = ImageSelectionRequest(
        article_text=article_text,
        explicit_query=explicit_query,
        num_images=num_images,
        enable_llm=enable_llm,
        llm_config=llm_config,
        search_config=search_config,
        supabase_config=supabase_config,
    )
    request_model.validate()
    return request_model
