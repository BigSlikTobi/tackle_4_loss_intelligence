"""Service layer for Gemini TTS batch processing."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from pydub import AudioSegment

from src.shared.db.connection import SupabaseConfig, get_supabase_client
from src.shared.utils.env import get_required_env, load_env

from .config import (
    BatchItem,
    CreateBatchRequest,
    ProcessBatchRequest,
    StatusBatchRequest,
    TTSDirection,
    TTSScript,
)


class TTSBatchService:
    """Orchestrates Gemini batch creation, status checks, and result processing."""

    MODEL_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model_name}"

    def __init__(self, *, work_dir: Optional[Path] = None) -> None:
        self.work_dir = work_dir or (Path(tempfile.gettempdir()) / "gemini_tts_batch")
        self.work_dir.mkdir(parents=True, exist_ok=True)

    async def create_batch(self, request: CreateBatchRequest) -> dict[str, Any]:
        api_key = self._resolve_gemini_api_key(request)
        model_info = await self._fetch_model_metadata(
            api_key=api_key,
            model_name=request.model_name,
        )
        supported_methods = model_info.get("supportedGenerationMethods", [])
        if "batchGenerateContent" not in supported_methods:
            raise ValueError(
                f"Model {request.model_name} does not support batchGenerateContent"
            )

        batch_file = self._write_batch_file(request)
        client = self._create_genai_client(api_key)
        uploaded_file = await asyncio.to_thread(self._upload_batch_file, client, batch_file)
        batch_job = await asyncio.to_thread(
            self._create_batch_job,
            client,
            request.model_name,
            uploaded_file.name,
            f"gemini-tts-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        )

        status = self._serialize_batch(batch_job)
        status.update(
            {
                "model_name": request.model_name,
                "total_items": len(request.items),
                "input_file_name": getattr(uploaded_file, "name", None),
                "local_input_file": str(batch_file),
                "supported_generation_methods": supported_methods,
            }
        )
        return status

    async def check_status(self, request: StatusBatchRequest) -> dict[str, Any]:
        client = self._create_genai_client(self._resolve_gemini_api_key(request))
        batch_job = await asyncio.to_thread(self._get_batch_job, client, request.batch_id)
        return self._serialize_batch(batch_job)

    async def process_batch(self, request: ProcessBatchRequest) -> dict[str, Any]:
        client = self._create_genai_client(self._resolve_gemini_api_key(request))
        batch_job = await asyncio.to_thread(self._get_batch_job, client, request.batch_id)
        batch_info = self._serialize_batch(batch_job)
        batch_state = batch_info.get("status")
        if batch_state != "JOB_STATE_SUCCEEDED":
            raise ValueError(
                f"Batch {request.batch_id} is not complete. Current status: {batch_state}"
            )

        result_file_name = batch_info.get("output_file_id")
        if not result_file_name:
            raise ValueError(f"Batch {request.batch_id} has no output file")

        output_text = await asyncio.to_thread(self._download_file_text, client, result_file_name)
        supabase = self._create_supabase_client(request.supabase.url, request.supabase.key)
        results: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        for raw_line in output_text.splitlines():
            if not raw_line.strip():
                continue

            entry = json.loads(raw_line)
            item_id = entry.get("key")
            if entry.get("error"):
                response = entry.get("response") or {}
                failures.append(
                    {
                        "id": item_id,
                        "error": entry["error"],
                        "token_usage": self._extract_token_usage(response),
                    }
                )
                continue

            response = entry.get("response")
            if not response:
                failures.append(
                    {
                        "id": item_id,
                        "error": "Missing response payload",
                    }
                )
                continue

            inline_data = self._extract_inline_data(response)
            token_usage = self._extract_token_usage(response)
            if inline_data is None:
                failures.append(
                    {
                        "id": item_id,
                        "error": "No audio inlineData found in batch response",
                        "token_usage": token_usage,
                    }
                )
                continue

            source_mime_type = inline_data.get("mimeType", "audio/wav")
            audio_bytes = base64.b64decode(inline_data["data"])
            mp3_bytes = self._ensure_mp3(audio_bytes, source_mime_type)
            storage_path = self._build_storage_path(
                path_prefix=request.supabase.path_prefix,
                batch_id=request.batch_id,
                item_id=item_id or "unknown",
            )
            public_url = await asyncio.to_thread(
                self._upload_bytes_to_supabase,
                supabase,
                request.supabase.bucket,
                storage_path,
                mp3_bytes,
                "audio/mpeg",
                request.supabase.url,
            )
            results.append(
                {
                    "id": item_id,
                    "storage_path": storage_path,
                    "mime_type": "audio/mpeg",
                    "source_mime_type": source_mime_type,
                    "public_url": public_url,
                    "token_usage": token_usage,
                }
            )

        aggregated_token_usage = self._aggregate_token_usage(results, failures)
        processed_at = datetime.now(timezone.utc).isoformat()
        local_usage_summary_path = self._write_local_usage_summary(
            batch_id=request.batch_id,
            token_usage=aggregated_token_usage,
            processed_count=len(results),
            failed_count=len(failures),
            processed_at=processed_at,
        )
        manifest = {
            "batch_id": request.batch_id,
            "status": batch_state,
            "output_file_id": result_file_name,
            "processed_count": len(results),
            "failed_count": len(failures),
            "token_usage": aggregated_token_usage,
            "items": results,
            "failures": failures,
            "processed_at": processed_at,
            "local_usage_summary_file": str(local_usage_summary_path),
        }
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        manifest_path = f"{request.supabase.path_prefix.rstrip('/')}/{request.batch_id}/manifest.json"
        manifest_public_url = await asyncio.to_thread(
            self._upload_bytes_to_supabase,
            supabase,
            request.supabase.bucket,
            manifest_path,
            manifest_bytes,
            "application/json",
            request.supabase.url,
        )
        usage_summary = {
            "batch_id": request.batch_id,
            "status": batch_state,
            "processed_count": len(results),
            "failed_count": len(failures),
            "token_usage": aggregated_token_usage,
            "processed_at": processed_at,
            "manifest_path": manifest_path,
        }
        usage_summary_path = (
            f"{request.supabase.path_prefix.rstrip('/')}/{request.batch_id}/usage_summary.json"
        )
        usage_summary_public_url = await asyncio.to_thread(
            self._upload_bytes_to_supabase,
            supabase,
            request.supabase.bucket,
            usage_summary_path,
            json.dumps(usage_summary, indent=2).encode("utf-8"),
            "application/json",
            request.supabase.url,
        )

        return {
            "batch_id": request.batch_id,
            "status": batch_state,
            "processed_count": len(results),
            "failed_count": len(failures),
            "token_usage": aggregated_token_usage,
            "local_usage_summary_file": str(local_usage_summary_path),
            "usage_summary_path": usage_summary_path,
            "usage_summary_public_url": usage_summary_public_url,
            "manifest_path": manifest_path,
            "manifest_public_url": manifest_public_url,
            "items": results,
            "failures": failures,
        }

    async def _fetch_model_metadata(self, *, api_key: str, model_name: str) -> dict[str, Any]:
        url = self.MODEL_ENDPOINT.format(model_name=model_name)
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params={"key": api_key}, timeout=30.0)
            if response.status_code != 200:
                raise RuntimeError(
                    f"Failed to fetch Gemini model metadata ({response.status_code}): {response.text}"
                )
            return response.json()

    def _write_batch_file(self, request: CreateBatchRequest) -> Path:
        file_name = f"gemini_tts_batch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.jsonl"
        file_path = self.work_dir / file_name
        with file_path.open("w", encoding="utf-8") as handle:
            for item in request.items:
                record = {
                    "key": item.id,
                    "request": {
                        "contents": [
                            {
                                "role": "user",
                                "parts": [{"text": self._render_item_prompt(item)}],
                            }
                        ],
                        "generation_config": {
                            "responseModalities": ["AUDIO"],
                            "speechConfig": {
                                "voiceConfig": {
                                    "prebuiltVoiceConfig": {
                                        "voiceName": item.voice_name or request.voice_name
                                    }
                                }
                            },
                        },
                    },
                }
                handle.write(json.dumps(record) + "\n")
        return file_path

    def _render_item_prompt(self, item: BatchItem) -> str:
        if item.text and not any([item.tts_prompt, item.direction, item.script, item.title]):
            return item.text.strip()

        parts: list[str] = []
        if item.title:
            parts.append(f"Title: {item.title.strip()}")

        if item.tts_prompt:
            parts.append(item.tts_prompt.strip())
        else:
            direction_text = self._render_direction(item.direction)
            if direction_text:
                parts.append(direction_text)

            script_text = self._render_script(item.script)
            if script_text:
                parts.append(script_text)

            if item.text:
                parts.append(f"Text:\n{item.text.strip()}")

        rendered = "\n\n".join(part for part in parts if part).strip()
        if not rendered:
            raise ValueError(f"Item {item.id} did not render to a prompt")
        return rendered

    def _resolve_gemini_api_key(self, request: Any) -> str:
        credentials = getattr(request, "credentials", None)
        if credentials and getattr(credentials, "gemini", None):
            return credentials.gemini

        load_env()
        try:
            return get_required_env("GEMINI_API_KEY")
        except ValueError as exc:
            raise ValueError(
                "Gemini API key is required. Provide credentials.gemini or set GEMINI_API_KEY in the environment/.env."
            ) from exc

    def _render_direction(self, direction: Optional[TTSDirection]) -> str:
        if direction is None:
            return ""

        lines: list[str] = []
        if direction.audio_profile:
            lines.append(f"Audio Profile: {direction.audio_profile.strip()}")
        if direction.scene:
            lines.append(f"Scene: {direction.scene.strip()}")
        if direction.audience:
            lines.append(f"Audience: {direction.audience.strip()}")
        if direction.director_notes:
            lines.append(f"Director's Notes: {direction.director_notes.strip()}")
        if direction.pace:
            lines.append(f"Pace: {direction.pace.strip()}")
        if direction.warmth:
            lines.append(f"Warmth: {direction.warmth.strip()}")
        if direction.must_hit:
            lines.append("Must-Hit Phrases:")
            lines.extend(f"- {phrase.strip()}" for phrase in direction.must_hit if phrase.strip())
        if direction.pronunciations:
            lines.append("Pronunciations:")
            lines.extend(
                f"- {guide.term.strip()}: {guide.guide.strip()}"
                for guide in direction.pronunciations
            )
        return "\n".join(lines).strip()

    def _render_script(self, script: Optional[TTSScript]) -> str:
        if script is None:
            return ""

        lines = ["Script:"]
        if script.intro:
            lines.append(f"Intro: {script.intro.strip()}")
        if script.body:
            lines.append(f"Body: {script.body.strip()}")
        if script.outro:
            lines.append(f"Outro: {script.outro.strip()}")
        return "\n\n".join(lines).strip()

    def _create_genai_client(self, api_key: str) -> Any:
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "google-genai is required for gemini_tts_batch. Install module dependencies first."
            ) from exc
        return genai.Client(api_key=api_key)

    def _upload_batch_file(self, client: Any, batch_file: Path) -> Any:
        try:
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "google-genai is required for gemini_tts_batch. Install module dependencies first."
            ) from exc

        return client.files.upload(
            file=str(batch_file),
            config=types.UploadFileConfig(
                display_name=batch_file.stem,
                mime_type="jsonl",
            ),
        )

    def _create_batch_job(
        self,
        client: Any,
        model_name: str,
        input_file_name: str,
        display_name: str,
    ) -> Any:
        return client.batches.create(
            model=model_name,
            src=input_file_name,
            config={"display_name": display_name},
        )

    def _get_batch_job(self, client: Any, batch_id: str) -> Any:
        return client.batches.get(name=batch_id)

    def _download_file_text(self, client: Any, file_name: str) -> str:
        content = client.files.download(file=file_name)
        if isinstance(content, bytes):
            return content.decode("utf-8")
        if isinstance(content, str):
            return content
        if hasattr(content, "decode"):
            return content.decode("utf-8")
        raise RuntimeError(f"Unexpected file download type: {type(content)!r}")

    def _serialize_batch(self, batch_job: Any) -> dict[str, Any]:
        state = getattr(batch_job, "state", None)
        status = getattr(state, "name", state)
        dest = getattr(batch_job, "dest", None)
        error = getattr(batch_job, "error", None)
        return {
            "batch_id": getattr(batch_job, "name", None),
            "status": status,
            "created_at": self._coerce_value(getattr(batch_job, "create_time", None)),
            "updated_at": self._coerce_value(getattr(batch_job, "update_time", None)),
            "output_file_id": self._coerce_value(getattr(dest, "file_name", None)),
            "error_file_id": self._coerce_value(getattr(dest, "error_file_name", None)),
            "error": self._coerce_value(error),
        }

    def _coerce_value(self, value: Any) -> Any:
        if value is None:
            return None
        if hasattr(value, "name"):
            return value.name
        if hasattr(value, "message"):
            return getattr(value, "message")
        return value

    def _extract_inline_data(self, response_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        candidates = response_payload.get("candidates") or []
        if not candidates:
            return None
        content = candidates[0].get("content") or {}
        for part in content.get("parts") or []:
            inline_data = part.get("inlineData")
            if inline_data:
                return inline_data
        return None

    def _extract_token_usage(self, response_payload: dict[str, Any]) -> dict[str, Optional[int]]:
        usage = response_payload.get("usageMetadata") or response_payload.get("usage_metadata") or {}
        return {
            "input_tokens": self._read_usage_int(usage, "promptTokenCount", "prompt_token_count"),
            "cached_input_tokens": self._read_usage_int(
                usage,
                "cachedContentTokenCount",
                "cached_content_token_count",
            ),
            "output_tokens": self._read_usage_int(
                usage,
                "candidatesTokenCount",
                "candidates_token_count",
            ),
            "total_tokens": self._read_usage_int(usage, "totalTokenCount", "total_token_count"),
        }

    def _read_usage_int(self, usage: dict[str, Any], *keys: str) -> Optional[int]:
        for key in keys:
            value = usage.get(key)
            if value is not None:
                return int(value)
        return None

    def _aggregate_token_usage(
        self,
        results: list[dict[str, Any]],
        failures: list[dict[str, Any]],
    ) -> dict[str, int]:
        aggregate = {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "reported_item_count": 0,
        }

        for item in [*results, *failures]:
            usage = item.get("token_usage") or {}
            if not any(value is not None for value in usage.values()):
                continue
            aggregate["reported_item_count"] += 1
            for key in ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens"):
                value = usage.get(key)
                if value is not None:
                    aggregate[key] += int(value)

        return aggregate

    def _write_local_usage_summary(
        self,
        *,
        batch_id: str,
        token_usage: dict[str, int],
        processed_count: int,
        failed_count: int,
        processed_at: str,
    ) -> Path:
        summary = {
            "batch_id": batch_id,
            "processed_count": processed_count,
            "failed_count": failed_count,
            "token_usage": token_usage,
            "processed_at": processed_at,
        }
        file_path = self.work_dir / f"{self._safe_batch_id(batch_id)}_usage_summary.json"
        with file_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2)
        return file_path

    def _safe_batch_id(self, batch_id: str) -> str:
        return batch_id.replace("/", "_")

    def _ensure_mp3(self, audio_bytes: bytes, mime_type: str) -> bytes:
        if "mpeg" in mime_type.lower() or "mp3" in mime_type.lower():
            return audio_bytes

        if "l16" in mime_type.lower() or "pcm" in mime_type.lower():
            sample_rate = 24000
            if "rate=" in mime_type:
                try:
                    rate_str = mime_type.split("rate=")[1].split(";")[0].split(",")[0]
                    sample_rate = int(rate_str)
                except ValueError:
                    sample_rate = 24000
            audio = AudioSegment(
                data=audio_bytes,
                sample_width=2,
                frame_rate=sample_rate,
                channels=1,
            )
        elif "wav" in mime_type.lower():
            audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="wav")
        else:
            audio = AudioSegment.from_file(io.BytesIO(audio_bytes))

        buffer = io.BytesIO()
        audio.export(buffer, format="mp3", bitrate="192k")
        return buffer.getvalue()

    def _build_storage_path(self, *, path_prefix: str, batch_id: str, item_id: str) -> str:
        prefix = path_prefix.rstrip("/")
        return f"{prefix}/{batch_id}/{item_id}.mp3"

    def _create_supabase_client(self, url: str, key: str) -> Any:
        return get_supabase_client(SupabaseConfig(url=url, key=key))

    def _upload_bytes_to_supabase(
        self,
        supabase: Any,
        bucket: str,
        path: str,
        payload: bytes,
        content_type: str,
        supabase_url: str,
    ) -> str:
        public_url = f"{supabase_url.rstrip('/')}/storage/v1/object/public/{bucket}/{path}"
        try:
            response = supabase.storage.from_(bucket).upload(
                path=path,
                file=payload,
                file_options={"contentType": content_type},
            )
            if isinstance(response, dict) and response.get("error"):
                error_text = str(response["error"]).lower()
                if "duplicate" in error_text or "exists" in error_text or "already" in error_text:
                    return public_url
                raise RuntimeError(str(response["error"]))
        except Exception as exc:
            error_text = str(exc).lower()
            if "duplicate" in error_text or "exists" in error_text or "already" in error_text:
                return public_url
            raise RuntimeError(f"Failed to upload {path} to Supabase: {exc}") from exc
        return public_url
