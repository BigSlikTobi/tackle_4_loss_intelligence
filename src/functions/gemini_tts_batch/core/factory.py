"""Factories for Gemini TTS batch requests."""

from __future__ import annotations

from typing import Any, Dict

from .config import (
    BatchActionRequest,
    CreateBatchRequest,
    ProcessBatchRequest,
    StatusBatchRequest,
)


class TTSBatchFactory:
    """Parse and validate incoming batch requests."""

    @staticmethod
    def create_request(payload: Dict[str, Any]) -> BatchActionRequest:
        if not isinstance(payload, dict):
            raise ValueError("Request payload must be a JSON object")

        action = payload.get("action")
        try:
            if action == "create":
                return CreateBatchRequest(**payload)
            if action == "status":
                return StatusBatchRequest(**payload)
            if action == "process":
                return ProcessBatchRequest(**payload)
        except Exception as exc:
            raise ValueError(f"Invalid request format: {exc}") from exc

        raise ValueError("action must be one of: create, status, process")
