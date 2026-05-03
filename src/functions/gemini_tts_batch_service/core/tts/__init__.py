"""TTS batch implementation owned by gemini_tts_batch_service.

Kept inside the service module to preserve function-based isolation: the
async submit/poll/worker wrapper must not import from another function
module. This is a deliberate copy of the legacy ``gemini_tts_batch``
implementation; once Phase C of the migration retires the legacy module,
this becomes the single home for the TTS batch logic.
"""

from .config import (
    BatchActionRequest,
    BatchItem,
    CreateBatchRequest,
    Credentials,
    PronunciationGuide,
    ProcessBatchRequest,
    StatusBatchRequest,
    SupabaseStorageConfig,
    TTSDirection,
    TTSScript,
)
from .service import TTSBatchService

__all__ = [
    "BatchActionRequest",
    "BatchItem",
    "CreateBatchRequest",
    "Credentials",
    "PronunciationGuide",
    "ProcessBatchRequest",
    "StatusBatchRequest",
    "SupabaseStorageConfig",
    "TTSBatchService",
    "TTSDirection",
    "TTSScript",
]
