"""Backwards-compat re-export shim.

Extractors moved to ``src.shared.extractors``. Existing imports keep working
via these re-exports; new code should import directly from ``src.shared``.
"""

from src.shared.extractors import extractor_factory, light_extractor, playwright_extractor  # noqa: F401
from src.shared.extractors.extractor_factory import (  # noqa: F401
    get_extractor,
    is_heavy_url,
)
