"""Request factory that parses incoming payloads into ``ValidationRequest`` objects."""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional

from src.shared.utils.env import get_env, load_env
from src.shared.utils.logging import get_logger

from .config import LLMConfig, SupabaseConfig, ValidationConfig
from .contracts import ValidationRequest

LOGGER = get_logger(__name__)

_BOOL_TRUE = {"true", "1", "yes", "on"}
_BOOL_FALSE = {"false", "0", "no", "off"}

_DEFAULT_LLM_MODEL = "gemini-2.5-flash-lite"
_DEFAULT_LLM_TIMEOUT = 60
_DEFAULT_VALIDATION_TIMEOUT = 90


def request_from_payload(payload: Mapping[str, Any]) -> ValidationRequest:
    """Build a ``ValidationRequest`` from a raw payload mapping."""

    if not isinstance(payload, Mapping):
        raise ValueError("Payload must be a mapping")

    load_env()

    try:
        article = payload["article"]
    except KeyError as exc:
        raise ValueError("`article` field is required") from exc

    try:
        article_type = payload["article_type"]
    except KeyError as exc:
        raise ValueError("`article_type` field is required") from exc

    llm_config = _build_llm_config(payload.get("llm"))
    validation_config = _build_validation_config(payload.get("validation_config"))
    supabase_config = _build_supabase_config(payload.get("supabase"))

    request = ValidationRequest(
        article=article,
        article_type=article_type,
        team_context=payload.get("team_context"),
        source_summaries=_resolve_source_summaries(payload.get("source_summaries")),
        quality_standards=_coerce_mapping(payload.get("quality_standards")),
        llm_config=llm_config,
        validation_config=validation_config,
        supabase_config=supabase_config,
    )
    return request


def _resolve_source_summaries(value: Any) -> Optional[list[str]]:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    raise ValueError("`source_summaries` must be a sequence of strings")


def _coerce_mapping(value: Any) -> Optional[MutableMapping[str, Any]]:
    if value is None:
        return None
    if isinstance(value, MutableMapping):
        return dict(value)
    if isinstance(value, Mapping):
        return dict(value.items())
    raise ValueError("Expected a mapping for `quality_standards`")


def _build_llm_config(block: Any) -> LLMConfig:
    data = _mapping_or_none(block, "llm")
    api_key = _first_non_empty(
        data.get("api_key") if data else None,
        get_env("GEMINI_API_KEY"),
        get_env("GOOGLE_API_KEY"),
        get_env("OPENAI_API_KEY"),
    )
    if not api_key:
        raise ValueError(
            "Gemini API key must be provided via `llm.api_key` or GEMINI_API_KEY/GOOGLE_API_KEY env"
        )

    model = _first_non_empty(
        data.get("model") if data else None,
        get_env("GEMINI_MODEL"),
        get_env("GOOGLE_MODEL"),
        get_env("OPENAI_MODEL"),
        _DEFAULT_LLM_MODEL,
    )

    timeout_seconds = _coerce_int(
        _first_non_none(
            data.get("timeout_seconds") if data else None,
            get_env("GEMINI_TIMEOUT_SECONDS"),
            get_env("GOOGLE_TIMEOUT_SECONDS"),
            get_env("OPENAI_TIMEOUT_SECONDS"),
            _DEFAULT_LLM_TIMEOUT,
        ),
        field_name="llm.timeout_seconds",
    )

    enable_web_search = _coerce_bool(
        _first_non_none(
            data.get("enable_web_search") if data else None,
            get_env("GEMINI_ENABLE_WEB_SEARCH"),
            get_env("GOOGLE_ENABLE_WEB_SEARCH"),
            get_env("OPENAI_ENABLE_WEB_SEARCH"),
            True,
        ),
        field_name="llm.enable_web_search",
    )

    config = LLMConfig(
        model=model,
        api_key=api_key,
        enable_web_search=enable_web_search,
        timeout_seconds=timeout_seconds,
    )
    config.validate()
    return config


def _build_validation_config(block: Any) -> ValidationConfig:
    data = _mapping_or_none(block, "validation_config") or {}

    timeout_seconds = _coerce_int(
        _first_non_none(
            data.get("timeout_seconds"),
            get_env("VALIDATION_TIMEOUT_SECONDS"),
            _DEFAULT_VALIDATION_TIMEOUT,
        ),
        field_name="validation.timeout_seconds",
    )

    config = ValidationConfig(
        enable_factual=_coerce_bool(
            data.get("enable_factual", True),
            field_name="validation.enable_factual",
        ),
        enable_contextual=_coerce_bool(
            data.get("enable_contextual", True),
            field_name="validation.enable_contextual",
        ),
        enable_quality=_coerce_bool(
            data.get("enable_quality", True),
            field_name="validation.enable_quality",
        ),
        factual_threshold=_coerce_float(
            data.get("factual_threshold", 0.7),
            field_name="validation.factual_threshold",
        ),
        contextual_threshold=_coerce_float(
            data.get("contextual_threshold", 0.7),
            field_name="validation.contextual_threshold",
        ),
        quality_threshold=_coerce_float(
            data.get("quality_threshold", 0.7),
            field_name="validation.quality_threshold",
        ),
        confidence_threshold=_coerce_float(
            data.get("confidence_threshold", 0.8),
            field_name="validation.confidence_threshold",
        ),
        timeout_seconds=timeout_seconds,
    )
    config.validate()
    return config


def _build_supabase_config(block: Any) -> Optional[SupabaseConfig]:
    if block is None:
        LOGGER.debug("No Supabase configuration provided; persistence disabled")
        return None

    data = _mapping_or_none(block, "supabase")
    if not data:
        return None

    url = _first_non_empty(data.get("url"), get_env("SUPABASE_URL"))
    key = _first_non_empty(data.get("key"), get_env("SUPABASE_KEY"))
    table = _first_non_empty(data.get("table"), get_env("SUPABASE_TABLE"), "article_validations")
    schema = _first_non_empty_optional(data.get("schema"))

    if not url or not key:
        raise ValueError("Supabase url and key must be provided when supabase block is present")

    config = SupabaseConfig(url=url, key=key, table=table, schema=schema)
    config.validate()
    return config


def _mapping_or_none(value: Any, label: str) -> Optional[Mapping[str, Any]]:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value
    raise ValueError(f"`{label}` block must be a mapping when provided")


def _first_non_empty(*values: Optional[Any]) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_non_empty_optional(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _first_non_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _coerce_bool(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _BOOL_TRUE:
            return True
        if lowered in _BOOL_FALSE:
            return False
    if value is None:
        raise ValueError(f"{field_name} must be provided")
    raise ValueError(f"{field_name} must be a boolean value")


def _coerce_int(value: Any, field_name: str) -> int:
    if value is None:
        raise ValueError(f"{field_name} must be provided")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _coerce_float(value: Any, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc