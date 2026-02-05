"""Vision-based image validation using OCR and CLIP embeddings.

This module provides validation capabilities to detect:
- Text overlays (broadcast graphics, scores, watermarks)
- Semantic relevance (image-query alignment via CLIP)
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Lazy imports for optional dependencies
_vision_client = None
_clip_model = None
_clip_processor = None


@dataclass
class VisionConfig:
    """Configuration for vision-based validation."""

    enabled: bool = True
    google_cloud_credentials: Optional[str] = None  # JSON key string or file path
    clip_model: str = "openai/clip-vit-base-patch32"
    text_rejection_threshold: int = 15  # Max characters allowed
    similarity_threshold: float = 0.25  # Min CLIP similarity score
    enable_ocr: bool = True
    enable_clip: bool = True


@dataclass
class TextDetectionResult:
    """Result of OCR text detection on an image."""

    detected_text: str
    character_count: int
    contains_score_pattern: bool
    contains_overlay_words: bool
    should_reject: bool
    rejection_reason: Optional[str] = None


@dataclass
class ValidationResult:
    """Combined result of all vision-based validations."""

    passed: bool
    text_result: Optional[TextDetectionResult] = None
    clip_similarity: Optional[float] = None
    reason: Optional[str] = None


# Common overlay text patterns to detect and reject
OVERLAY_WORDS = {
    "live",
    "breaking",
    "exclusive",
    "replay",
    "highlight",
    "stats",
    "score",
    "final",
    "halftime",
    "quarter",
    "down",
    "yards",
    "touchdown",
    "field goal",
    "interception",
    "fumble",
    "penalty",
    "timeout",
    "review",
    "nfl",
    "espn",
    "fox",
    "cbs",
    "nbc",
    "abc",
    "prime",
    "sunday",
    "monday",
    "thursday",
}

# Score patterns like "24-17", "3-0", "14 - 7"
SCORE_PATTERN = re.compile(r"\b\d{1,2}\s*[-–—]\s*\d{1,2}\b")


def _get_vision_client():
    """Lazy-load Google Cloud Vision client."""
    global _vision_client
    if _vision_client is None:
        try:
            from google.cloud import vision

            _vision_client = vision.ImageAnnotatorClient()
            logger.info("Google Cloud Vision client initialized")
        except ImportError:
            logger.warning(
                "google-cloud-vision not installed, OCR will be disabled"
            )
            return None
        except Exception as exc:
            logger.warning("Failed to initialize Vision client: %s", exc)
            return None
    return _vision_client


def _get_clip_model(model_name: str):
    """Lazy-load CLIP model and processor."""
    global _clip_model, _clip_processor
    if _clip_model is None:
        try:
            from transformers import CLIPModel, CLIPProcessor

            logger.info("Loading CLIP model: %s", model_name)
            _clip_model = CLIPModel.from_pretrained(model_name)
            _clip_processor = CLIPProcessor.from_pretrained(model_name)
            logger.info("CLIP model loaded successfully")
        except ImportError:
            logger.warning(
                "transformers/torch not installed, CLIP will be disabled"
            )
            return None, None
        except Exception as exc:
            logger.warning("Failed to load CLIP model: %s", exc)
            return None, None
    return _clip_model, _clip_processor


class VisionValidator:
    """Validates images using vision AI to detect text and assess relevance."""

    def __init__(self, config: VisionConfig) -> None:
        self.config = config
        self._vision_client = None
        self._clip_model = None
        self._clip_processor = None

        if config.enable_ocr:
            self._vision_client = _get_vision_client()

        if config.enable_clip:
            self._clip_model, self._clip_processor = _get_clip_model(
                config.clip_model
            )

    async def detect_text(self, image_bytes: bytes) -> TextDetectionResult:
        """Use Google Cloud Vision OCR to detect overlay text in image.

        Args:
            image_bytes: Raw image bytes to analyze.

        Returns:
            TextDetectionResult with detected text and rejection decision.
        """
        if not self._vision_client:
            return TextDetectionResult(
                detected_text="",
                character_count=0,
                contains_score_pattern=False,
                contains_overlay_words=False,
                should_reject=False,
                rejection_reason="OCR disabled",
            )

        def _detect() -> TextDetectionResult:
            from google.cloud import vision

            image = vision.Image(content=image_bytes)
            response = self._vision_client.text_detection(image=image)

            if response.error.message:
                logger.warning("Vision API error: %s", response.error.message)
                return TextDetectionResult(
                    detected_text="",
                    character_count=0,
                    contains_score_pattern=False,
                    contains_overlay_words=False,
                    should_reject=False,
                    rejection_reason=f"API error: {response.error.message}",
                )

            # Extract all detected text
            texts = response.text_annotations
            if not texts:
                return TextDetectionResult(
                    detected_text="",
                    character_count=0,
                    contains_score_pattern=False,
                    contains_overlay_words=False,
                    should_reject=False,
                )

            # First annotation contains the full detected text
            full_text = texts[0].description if texts else ""
            cleaned_text = " ".join(full_text.split())
            char_count = len(cleaned_text)

            # Check for score patterns
            has_score = bool(SCORE_PATTERN.search(cleaned_text))

            # Check for overlay words
            text_lower = cleaned_text.lower()
            has_overlay_words = any(word in text_lower for word in OVERLAY_WORDS)

            # Determine rejection
            should_reject = False
            rejection_reason = None

            if char_count > self.config.text_rejection_threshold:
                should_reject = True
                rejection_reason = (
                    f"Too much text detected ({char_count} chars > "
                    f"{self.config.text_rejection_threshold} threshold)"
                )
            elif has_score:
                should_reject = True
                rejection_reason = "Score pattern detected (likely broadcast graphic)"
            elif has_overlay_words and char_count > 5:
                should_reject = True
                rejection_reason = f"Overlay words detected: {cleaned_text[:50]}"

            return TextDetectionResult(
                detected_text=cleaned_text[:200],  # Truncate for logging
                character_count=char_count,
                contains_score_pattern=has_score,
                contains_overlay_words=has_overlay_words,
                should_reject=should_reject,
                rejection_reason=rejection_reason,
            )

        return await asyncio.to_thread(_detect)

    async def compute_clip_similarity(
        self, image_bytes: bytes, query: str
    ) -> float:
        """Compute CLIP embedding similarity between image and query.

        Args:
            image_bytes: Raw image bytes.
            query: Text query to compare against.

        Returns:
            Similarity score between 0.0 and 1.0.
        """
        if not self._clip_model or not self._clip_processor:
            logger.debug("CLIP not available, returning neutral score")
            return 0.5

        def _compute() -> float:
            import torch
            from PIL import Image

            # Load image
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

            # Process inputs
            inputs = self._clip_processor(
                text=[query],
                images=image,
                return_tensors="pt",
                padding=True,
            )

            # Compute embeddings
            with torch.no_grad():
                outputs = self._clip_model(**inputs)
                image_embeds = outputs.image_embeds
                text_embeds = outputs.text_embeds

                # Normalize embeddings
                image_embeds = image_embeds / image_embeds.norm(
                    p=2, dim=-1, keepdim=True
                )
                text_embeds = text_embeds / text_embeds.norm(
                    p=2, dim=-1, keepdim=True
                )

                # Compute cosine similarity
                similarity = torch.matmul(
                    image_embeds, text_embeds.transpose(0, 1)
                )
                score = similarity.item()

                # Normalize to 0-1 range (CLIP scores are typically -1 to 1)
                normalized_score = (score + 1) / 2
                return max(0.0, min(1.0, normalized_score))

        try:
            return await asyncio.to_thread(_compute)
        except Exception as exc:
            logger.warning("CLIP similarity computation failed: %s", exc)
            return 0.5

    async def validate_image(
        self, image_bytes: bytes, query: str
    ) -> ValidationResult:
        """Perform full vision-based validation on an image.

        Args:
            image_bytes: Raw image bytes to validate.
            query: Search query for semantic relevance check.

        Returns:
            ValidationResult indicating pass/fail and reasons.
        """
        if not self.config.enabled:
            return ValidationResult(passed=True, reason="Vision validation disabled")

        text_result: Optional[TextDetectionResult] = None
        clip_similarity: Optional[float] = None

        # Run OCR check
        if self.config.enable_ocr:
            text_result = await self.detect_text(image_bytes)
            if text_result.should_reject:
                return ValidationResult(
                    passed=False,
                    text_result=text_result,
                    reason=text_result.rejection_reason,
                )

        # Run CLIP similarity check
        if self.config.enable_clip:
            clip_similarity = await self.compute_clip_similarity(image_bytes, query)
            if clip_similarity < self.config.similarity_threshold:
                return ValidationResult(
                    passed=False,
                    text_result=text_result,
                    clip_similarity=clip_similarity,
                    reason=(
                        f"Low semantic relevance (CLIP score {clip_similarity:.2f} < "
                        f"{self.config.similarity_threshold} threshold)"
                    ),
                )

        return ValidationResult(
            passed=True,
            text_result=text_result,
            clip_similarity=clip_similarity,
        )

    async def batch_validate(
        self,
        images: List[Tuple[bytes, str]],
        max_concurrent: int = 5,
    ) -> List[ValidationResult]:
        """Validate multiple images concurrently.

        Args:
            images: List of (image_bytes, query) tuples.
            max_concurrent: Maximum concurrent validations.

        Returns:
            List of ValidationResults in same order as input.
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def validate_with_limit(
            image_bytes: bytes, query: str
        ) -> ValidationResult:
            async with semaphore:
                return await self.validate_image(image_bytes, query)

        tasks = [validate_with_limit(img, q) for img, q in images]
        return await asyncio.gather(*tasks)
