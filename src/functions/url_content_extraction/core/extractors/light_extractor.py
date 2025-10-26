"""HTTP-only extractor placeholder."""

from typing import Optional

from ..contracts.extracted_content import ExtractedContent


class LightExtractor:
    """Performs fast HTTP extraction for simple pages."""

    def extract(self, url: str, *, timeout: Optional[float] = None) -> ExtractedContent:
        """Stub for lightweight extraction logic."""
        return ExtractedContent(url=url, error="Light extractor not yet implemented")
