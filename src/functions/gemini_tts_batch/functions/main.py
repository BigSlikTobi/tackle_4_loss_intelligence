"""HTTP entry point for Gemini TTS batch processing."""

from __future__ import annotations

import asyncio

import functions_framework
from flask import Request, Response, jsonify

from ..core.config import CreateBatchRequest, ProcessBatchRequest, StatusBatchRequest
from ..core.factory import TTSBatchFactory
from ..core.service import TTSBatchService


def _cors_headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "3600",
    }


@functions_framework.http
def handle_tts_batch(request: Request) -> Response:
    if request.method == "OPTIONS":
        return Response("", 204, _cors_headers())

    headers = _cors_headers()
    try:
        payload = request.get_json(silent=True)
        if not payload:
            return Response("Invalid JSON payload", 400, headers)

        parsed_request = TTSBatchFactory.create_request(payload)
        service = TTSBatchService()

        if isinstance(parsed_request, CreateBatchRequest):
            result = asyncio.run(service.create_batch(parsed_request))
        elif isinstance(parsed_request, StatusBatchRequest):
            result = asyncio.run(service.check_status(parsed_request))
        elif isinstance(parsed_request, ProcessBatchRequest):
            result = asyncio.run(service.process_batch(parsed_request))
        else:  # pragma: no cover - defensive
            return Response("Unsupported action", 400, headers)

        response = jsonify(result)
        response.headers.update(headers)
        return response
    except ValueError as exc:
        return Response(str(exc), 400, headers)
    except RuntimeError as exc:
        return Response(str(exc), 502, headers)
    except Exception as exc:  # noqa: BLE001
        return Response(f"Internal Server Error: {exc}", 500, headers)
