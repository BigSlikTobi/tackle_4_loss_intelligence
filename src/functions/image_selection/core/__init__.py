"""Core services for the image_selection module.

SOTA Optimizations:
- Vision validation (OCR text detection + CLIP semantic similarity)
- Enhanced LLM query generation with visual intent classification
- Expanded domain blacklists and URL pattern filtering
- Source reputation scoring for trusted editorial sources
"""

from .config import (
    ImageSelectionRequest,
    LLMConfig,
    SearchConfig,
    SupabaseConfig,
    VisionConfig,
)
from .factory import request_from_payload
from .llm import create_llm_client
from .service import ImageSelectionService
from .source_reputation import get_source_score, get_source_score_from_url
from .vision_validator import VisionValidator, ValidationResult

__all__ = [
    "ImageSelectionRequest",
    "ImageSelectionService",
    "LLMConfig",
    "SearchConfig",
    "SupabaseConfig",
    "ValidationResult",
    "VisionConfig",
    "VisionValidator",
    "create_llm_client",
    "get_source_score",
    "get_source_score_from_url",
    "request_from_payload",
]
