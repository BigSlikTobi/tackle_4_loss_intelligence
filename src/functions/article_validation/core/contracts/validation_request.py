"""Request contract for the article validation module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, MutableMapping, Optional, Sequence, TYPE_CHECKING

from src.shared.utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - imported for type checkers only
    from ..config import LLMConfig, SupabaseConfig, ValidationConfig


_LOGGER = get_logger(__name__)


def _normalise_article(article: Any) -> MutableMapping[str, Any]:
    """Return the article payload as a mutable mapping.

    Accepts flexible structures: dictionaries are used as-is, strings are
    wrapped into a generic structure, and raises on unsupported types.
    """

    if isinstance(article, MutableMapping):
        return dict(article)

    if isinstance(article, Mapping):
        return dict(article.items())

    if isinstance(article, str):
        _LOGGER.debug("Wrapping string article content into generic structure")
        return {"content": article}

    raise ValueError("`article` must be a mapping or string containing article text")


def _normalise_summaries(summaries: Optional[Sequence[str]]) -> Optional[list[str]]:
    """Normalise summaries into a list of non-empty strings."""

    if summaries is None:
        return None

    cleaned: list[str] = []
    for summary in summaries:
        if summary is None:
            continue
        text = str(summary).strip()
        if text:
            cleaned.append(text)
    return cleaned or None


@dataclass
class ValidationRequest:
    """Incoming validation request payload."""

    article: MutableMapping[str, Any]
    article_type: str
    team_context: Optional[Mapping[str, Any]] = None
    source_summaries: Optional[list[str]] = field(default=None)
    quality_standards: Optional[Mapping[str, Any]] = None
    llm_config: Optional["LLMConfig"] = None
    validation_config: Optional["ValidationConfig"] = None
    supabase_config: Optional["SupabaseConfig"] = None

    def __post_init__(self) -> None:
        self.article = _normalise_article(self.article)
        self.article_type = self._normalise_article_type(self.article_type)
        self.source_summaries = _normalise_summaries(self.source_summaries)
        self._validate_team_context()
        self._validate_quality_standards()
        self._validate_optional_configs()

    @staticmethod
    def _normalise_article_type(article_type: Any) -> str:
        if not isinstance(article_type, str) or not article_type.strip():
            raise ValueError("`article_type` must be a non-empty string")
        return article_type.strip().lower()

    def _validate_team_context(self) -> None:
        if self.team_context is None:
            return
        if not isinstance(self.team_context, Mapping):
            raise ValueError("`team_context` must be a mapping when provided")
        if "team" not in self.team_context and "team_name" not in self.team_context:
            _LOGGER.debug("team_context missing explicit team key; proceeding regardless")

    def _validate_quality_standards(self) -> None:
        if self.quality_standards is None:
            return
        if not isinstance(self.quality_standards, Mapping):
            raise ValueError("`quality_standards` must be a mapping when provided")
        required_keys = {"quality_rules", "contextual_requirements", "factual_verification"}
        missing = [key for key in required_keys if key not in self.quality_standards]
        if missing:
            raise ValueError(
                "quality_standards missing required sections: " + ", ".join(missing)
            )

    def _validate_optional_configs(self) -> None:
        for config_obj, name in (
            (self.llm_config, "llm_config"),
            (self.validation_config, "validation_config"),
            (self.supabase_config, "supabase_config"),
        ):
            if config_obj is None:
                continue
            validate = getattr(config_obj, "validate", None)
            if callable(validate):
                validate()
            else:
                _LOGGER.debug("%s provided without explicit validate()" , name)

    def require_article_fields(self, required_fields: Iterable[str]) -> None:
        """Ensure the article mapping contains the supplied fields."""

        missing = [field for field in required_fields if field not in self.article]
        if missing:
            raise ValueError(
                "article payload missing required fields: " + ", ".join(sorted(missing))
            )
