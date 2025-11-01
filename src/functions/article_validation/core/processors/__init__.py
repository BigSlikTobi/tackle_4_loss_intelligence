"""Processing components for the article validation module."""

from .fact_checker import FactChecker, FactCheckerConfig
from .claim_extractor import ClaimCandidate, extract_claims
from .context_validator import ContextValidator, ContextValidatorConfig
from .quality_validator import QualityValidator, QualityValidatorConfig, resolve_quality_standards
from .decision_engine import DecisionEngine

__all__ = [
    "FactChecker",
    "FactCheckerConfig",
    "ClaimCandidate",
    "extract_claims",
    "ContextValidator",
    "ContextValidatorConfig",
    "QualityValidator",
    "QualityValidatorConfig",
    "resolve_quality_standards",
    "DecisionEngine",
]
