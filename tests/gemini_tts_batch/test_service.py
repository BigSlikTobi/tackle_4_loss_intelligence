import asyncio
import json
from types import SimpleNamespace

import pytest

from src.functions.gemini_tts_batch.core.config import (
    CreateBatchRequest,
    ProcessBatchRequest,
    StatusBatchRequest,
)
from src.functions.gemini_tts_batch.core.service import TTSBatchService


class FakeUploadedFile:
    def __init__(self, name: str):
        self.name = name


class FakeBatchClient:
    def __init__(self, batch_job):
        self.batch_job = batch_job
        self.upload_calls = []
        self.download_payload = b""
        self.batches = self
        self.files = self

    def upload(self, *, file, config):
        self.upload_calls.append((file, config))
        return FakeUploadedFile("files/input-123")

    def create(self, *, model, src, config):
        self.created = {"model": model, "src": src, "config": config}
        return self.batch_job

    def get(self, *, name):
        self.requested_batch = name
        return self.batch_job

    def download(self, *, file):
        self.downloaded_file = file
        return self.download_payload


class FakeStorageBucket:
    def __init__(self):
        self.uploads = []

    def upload(self, *, path, file, file_options):
        self.uploads.append((path, file, file_options))
        return {"path": path}


class FakeStorageRoot:
    def __init__(self):
        self.bucket = FakeStorageBucket()

    def from_(self, bucket):
        self.bucket_name = bucket
        return self.bucket


class FakeSupabase:
    def __init__(self):
        self.storage = FakeStorageRoot()


@pytest.fixture
def batch_job():
    return SimpleNamespace(
        name="batches/123",
        state=SimpleNamespace(name="JOB_STATE_SUCCEEDED"),
        dest=SimpleNamespace(file_name="files/output-123"),
        create_time="2026-03-09T12:00:00Z",
        update_time="2026-03-09T12:10:00Z",
        error=None,
    )


@pytest.fixture
def service(tmp_path):
    return TTSBatchService(work_dir=tmp_path)


def test_write_batch_file_uses_item_voice_override(service: TTSBatchService):
    request = CreateBatchRequest(
        action="create",
        model_name="gemini-2.5-pro-preview-tts",
        voice_name="Charon",
        items=[
            {"id": "story-1", "text": "Hello one"},
            {"id": "story-2", "text": "Hello two", "voice_name": "Kore"},
        ],
        credentials={"gemini": "key"},
    )

    batch_file = service._write_batch_file(request)
    lines = batch_file.read_text(encoding="utf-8").strip().splitlines()

    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["key"] == "story-1"
    assert second["key"] == "story-2"
    assert (
        first["request"]["generation_config"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"]
        == "Charon"
    )
    assert (
        second["request"]["generation_config"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"]
        == "Kore"
    )


def test_write_batch_file_renders_structured_prompt(service: TTSBatchService):
    request = CreateBatchRequest(
        action="create",
        model_name="gemini-2.5-pro-preview-tts",
        items=[
            {
                "id": "story-1",
                "title": "AFC East shockwave",
                "direction": {
                    "audio_profile": "Single-anchor, live-breaking NFL news hit",
                    "scene": "Top of the hour on a national NFL network",
                    "must_hit": ["record 99 million in dead money"],
                    "pronunciations": [
                        {"term": "Tagovailoa", "guide": "TAH-go-vai-LOH-uh"}
                    ],
                },
                "script": {
                    "intro": "Intro text",
                    "body": "Body text",
                    "outro": "Outro text",
                },
            }
        ],
        credentials={"gemini": "key"},
    )

    batch_file = service._write_batch_file(request)
    line = json.loads(batch_file.read_text(encoding="utf-8").strip())
    rendered = line["request"]["contents"][0]["parts"][0]["text"]

    assert "Title: AFC East shockwave" in rendered
    assert "Audio Profile: Single-anchor, live-breaking NFL news hit" in rendered
    assert "Must-Hit Phrases:" in rendered
    assert "- record 99 million in dead money" in rendered
    assert "Pronunciations:" in rendered
    assert "- Tagovailoa: TAH-go-vai-LOH-uh" in rendered
    assert "Script:" in rendered
    assert "Intro: Intro text" in rendered
    assert "Body: Body text" in rendered
    assert "Outro: Outro text" in rendered


def test_create_batch_rejects_model_without_batch_support(service: TTSBatchService):
    request = CreateBatchRequest(
        action="create",
        model_name="gemini-2.5-flash-preview-tts",
        items=[{"id": "story-1", "text": "Hello"}],
        credentials={"gemini": "key"},
    )

    async def fake_metadata(*, api_key, model_name):
        return {"supportedGenerationMethods": ["generateContent"]}

    service._fetch_model_metadata = fake_metadata  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="does not support batchGenerateContent"):
        asyncio.run(service.create_batch(request))


def test_resolve_gemini_api_key_from_request(service: TTSBatchService):
    request = StatusBatchRequest(
        action="status",
        batch_id="batches/123",
        credentials={"gemini": "request-key"},
    )

    assert service._resolve_gemini_api_key(request) == "request-key"


def test_resolve_gemini_api_key_from_env(monkeypatch, service: TTSBatchService):
    request = StatusBatchRequest(
        action="status",
        batch_id="batches/123",
    )
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    assert service._resolve_gemini_api_key(request) == "env-key"


def test_resolve_gemini_api_key_raises_when_missing(monkeypatch, service: TTSBatchService):
    request = StatusBatchRequest(
        action="status",
        batch_id="batches/123",
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(
        "src.functions.gemini_tts_batch.core.service.load_env",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(ValueError, match="Gemini API key is required"):
        service._resolve_gemini_api_key(request)


def test_create_batch_returns_batch_metadata(service: TTSBatchService, batch_job):
    request = CreateBatchRequest(
        action="create",
        model_name="gemini-2.5-pro-preview-tts",
        items=[{"id": "story-1", "text": "Hello"}],
        credentials={"gemini": "key"},
    )
    client = FakeBatchClient(batch_job)

    async def fake_metadata(*, api_key, model_name):
        return {"supportedGenerationMethods": ["generateContent", "batchGenerateContent"]}

    service._fetch_model_metadata = fake_metadata  # type: ignore[method-assign]
    service._create_genai_client = lambda api_key: client  # type: ignore[method-assign]
    service._upload_batch_file = lambda client, batch_file: FakeUploadedFile("files/input-123")  # type: ignore[method-assign]
    service._create_batch_job = lambda client, model_name, input_file_name, display_name: batch_job  # type: ignore[method-assign]

    result = asyncio.run(service.create_batch(request))

    assert result["batch_id"] == "batches/123"
    assert result["input_file_name"] == "files/input-123"
    assert result["total_items"] == 1


def test_check_status_returns_serialized_batch(service: TTSBatchService, batch_job):
    request = StatusBatchRequest(
        action="status",
        batch_id="batches/123",
        credentials={"gemini": "key"},
    )
    client = FakeBatchClient(batch_job)
    service._create_genai_client = lambda api_key: client  # type: ignore[method-assign]

    result = asyncio.run(service.check_status(request))

    assert result["status"] == "JOB_STATE_SUCCEEDED"
    assert result["output_file_id"] == "files/output-123"


def test_process_batch_uploads_audio_and_manifest(service: TTSBatchService, batch_job):
    request = ProcessBatchRequest(
        action="process",
        batch_id="batches/123",
        credentials={"gemini": "key"},
        supabase={"url": "https://example.supabase.co", "key": "supabase-key"},
    )
    client = FakeBatchClient(batch_job)
    client.download_payload = (
        b'{"key":"story-1","response":{"usageMetadata":{"promptTokenCount":120,"cachedContentTokenCount":30,"candidatesTokenCount":40,"totalTokenCount":160},"candidates":[{"content":{"parts":[{"inlineData":{"mimeType":"audio/mpeg","data":"QUJD"}}]}}]}}\n'
        b'{"key":"story-2","error":{"message":"failed"},"response":{"usageMetadata":{"promptTokenCount":10,"cachedContentTokenCount":0,"candidatesTokenCount":0,"totalTokenCount":10}}}\n'
    )
    fake_supabase = FakeSupabase()

    service._create_genai_client = lambda api_key: client  # type: ignore[method-assign]
    service._create_supabase_client = lambda url, key: fake_supabase  # type: ignore[method-assign]

    result = asyncio.run(service.process_batch(request))

    assert result["processed_count"] == 1
    assert result["failed_count"] == 1
    assert result["token_usage"] == {
        "input_tokens": 130,
        "cached_input_tokens": 30,
        "output_tokens": 40,
        "total_tokens": 170,
        "reported_item_count": 2,
    }
    assert result["items"][0]["token_usage"] == {
        "input_tokens": 120,
        "cached_input_tokens": 30,
        "output_tokens": 40,
        "total_tokens": 160,
    }
    assert result["usage_summary_path"] == "gemini-tts-batch/batches/123/usage_summary.json"
    assert result["usage_summary_public_url"].endswith(
        "/audio/gemini-tts-batch/batches/123/usage_summary.json"
    )
    assert result["local_usage_summary_file"].endswith("batches_123_usage_summary.json")
    uploaded_paths = [path for path, _, _ in fake_supabase.storage.bucket.uploads]
    assert "gemini-tts-batch/batches/123/story-1.mp3" in uploaded_paths
    assert "gemini-tts-batch/batches/123/manifest.json" in uploaded_paths
    assert "gemini-tts-batch/batches/123/usage_summary.json" in uploaded_paths
    local_summary_path = service.work_dir / "batches_123_usage_summary.json"
    assert local_summary_path.exists()
    local_summary = json.loads(local_summary_path.read_text(encoding="utf-8"))
    assert local_summary["token_usage"]["total_tokens"] == 170


def test_ensure_mp3_passthrough(service: TTSBatchService):
    payload = b"abc"
    assert service._ensure_mp3(payload, "audio/mpeg") == payload


def test_ensure_mp3_converts_wav(monkeypatch, service: TTSBatchService):
    exported = {}

    class FakeAudio:
        def export(self, buffer, format, bitrate):
            exported["format"] = format
            exported["bitrate"] = bitrate
            buffer.write(b"converted")

    monkeypatch.setattr(
        "src.functions.gemini_tts_batch.core.service.AudioSegment.from_file",
        lambda file_obj, format=None: FakeAudio(),
    )

    result = service._ensure_mp3(b"wav-bytes", "audio/wav")

    assert result == b"converted"
    assert exported == {"format": "mp3", "bitrate": "192k"}


def test_ensure_mp3_converts_pcm(monkeypatch, service: TTSBatchService):
    exported = {}

    class FakeAudio:
        def export(self, buffer, format, bitrate):
            exported["format"] = format
            exported["bitrate"] = bitrate
            buffer.write(b"converted")

    monkeypatch.setattr(
        "src.functions.gemini_tts_batch.core.service.AudioSegment",
        lambda **kwargs: FakeAudio(),
    )

    result = service._ensure_mp3(b"pcm-bytes", "audio/L16;rate=16000")

    assert result == b"converted"
    assert exported == {"format": "mp3", "bitrate": "192k"}


def test_upload_to_supabase_reuses_duplicate(service: TTSBatchService):
    class DuplicateBucket:
        def upload(self, *, path, file, file_options):
            raise RuntimeError("The resource already exists")

    class DuplicateStorage:
        def from_(self, bucket):
            return DuplicateBucket()

    class DuplicateSupabase:
        storage = DuplicateStorage()

    public_url = service._upload_bytes_to_supabase(
        DuplicateSupabase(),
        "audio",
        "gemini-tts-batch/batches/123/story-1.mp3",
        b"abc",
        "audio/mpeg",
        "https://example.supabase.co",
    )

    assert public_url.endswith("/audio/gemini-tts-batch/batches/123/story-1.mp3")


def test_extract_token_usage_supports_snake_case(service: TTSBatchService):
    usage = service._extract_token_usage(
        {
            "usage_metadata": {
                "prompt_token_count": 11,
                "cached_content_token_count": 2,
                "candidates_token_count": 5,
                "total_token_count": 16,
            }
        }
    )

    assert usage == {
        "input_tokens": 11,
        "cached_input_tokens": 2,
        "output_tokens": 5,
        "total_tokens": 16,
    }


# ---------------------------------------------------------------------------
# _render_item_prompt
# ---------------------------------------------------------------------------


def test_render_item_prompt_plain_text_fast_path(service: TTSBatchService):
    """Plain text with no title/direction/script/tts_prompt returns text as-is."""
    item = CreateBatchRequest(
        action="create",
        model_name="gemini-2.5-pro-preview-tts",
        items=[{"id": "s1", "text": "  Hello world  "}],
    ).items[0]

    assert service._render_item_prompt(item) == "Hello world"


def test_render_item_prompt_tts_prompt_only(service: TTSBatchService):
    """tts_prompt is returned verbatim (stripped) when it is the sole content field."""
    item = CreateBatchRequest(
        action="create",
        model_name="gemini-2.5-pro-preview-tts",
        items=[{"id": "s1", "tts_prompt": "  <speak>Go!</speak>  "}],
    ).items[0]

    assert service._render_item_prompt(item) == "<speak>Go!</speak>"


def test_render_item_prompt_title_with_text(service: TTSBatchService):
    """Title triggers the structured path; text is appended under a Text: header."""
    item = CreateBatchRequest(
        action="create",
        model_name="gemini-2.5-pro-preview-tts",
        items=[{"id": "s1", "title": "Big Game", "text": "The Eagles won."}],
    ).items[0]

    rendered = service._render_item_prompt(item)

    assert rendered.startswith("Title: Big Game")
    assert "Text:\nThe Eagles won." in rendered


def test_render_item_prompt_tts_prompt_overrides_direction(service: TTSBatchService):
    """When tts_prompt is present alongside direction, only tts_prompt is rendered."""
    item = CreateBatchRequest(
        action="create",
        model_name="gemini-2.5-pro-preview-tts",
        items=[
            {
                "id": "s1",
                "title": "Story",
                "tts_prompt": "Override prompt",
                "direction": {"audio_profile": "Ignored profile"},
            }
        ],
    ).items[0]

    rendered = service._render_item_prompt(item)

    assert "Override prompt" in rendered
    assert "Ignored profile" not in rendered


# ---------------------------------------------------------------------------
# _render_direction
# ---------------------------------------------------------------------------


def test_render_direction_returns_empty_for_none(service: TTSBatchService):
    assert service._render_direction(None) == ""


def test_render_direction_all_optional_fields(service: TTSBatchService):
    from src.functions.gemini_tts_batch.core.config import TTSDirection

    direction = TTSDirection(
        audio_profile="Tight, gritty newscaster",
        scene="Studio A at midnight",
        audience="NFL fans on mobile",
        director_notes="Open hot, slow down for cap numbers",
        pace="Fast with deliberate pauses",
        warmth="Cool and commanding",
        must_hit=["dead money record"],
        pronunciations=[{"term": "Tagovailoa", "guide": "TAH-go-vai-LOH-uh"}],
    )

    rendered = service._render_direction(direction)

    assert "Audio Profile: Tight, gritty newscaster" in rendered
    assert "Scene: Studio A at midnight" in rendered
    assert "Audience: NFL fans on mobile" in rendered
    assert "Director's Notes: Open hot, slow down for cap numbers" in rendered
    assert "Pace: Fast with deliberate pauses" in rendered
    assert "Warmth: Cool and commanding" in rendered
    assert "Must-Hit Phrases:" in rendered
    assert "- dead money record" in rendered
    assert "Pronunciations:" in rendered
    assert "- Tagovailoa: TAH-go-vai-LOH-uh" in rendered


# ---------------------------------------------------------------------------
# _render_script
# ---------------------------------------------------------------------------


def test_render_script_returns_empty_for_none(service: TTSBatchService):
    assert service._render_script(None) == ""


def test_render_script_body_only(service: TTSBatchService):
    from src.functions.gemini_tts_batch.core.config import TTSScript

    script = TTSScript(body="Body text only.")
    rendered = service._render_script(script)

    assert "Script:" in rendered
    assert "Body: Body text only." in rendered
    assert "Intro" not in rendered
    assert "Outro" not in rendered


# ---------------------------------------------------------------------------
# process_batch guards
# ---------------------------------------------------------------------------


def test_process_batch_raises_when_not_succeeded(service: TTSBatchService):
    """process_batch must reject batches that are not in JOB_STATE_SUCCEEDED."""
    from types import SimpleNamespace

    pending_job = SimpleNamespace(
        name="batches/456",
        state=SimpleNamespace(name="JOB_STATE_RUNNING"),
        dest=None,
        create_time=None,
        update_time=None,
        error=None,
    )
    request = ProcessBatchRequest(
        action="process",
        batch_id="batches/456",
        credentials={"gemini": "key"},
        supabase={"url": "https://example.supabase.co", "key": "supabase-key"},
    )
    client = FakeBatchClient(pending_job)
    service._create_genai_client = lambda api_key: client  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="not complete"):
        asyncio.run(service.process_batch(request))


def test_process_batch_raises_when_no_output_file(service: TTSBatchService):
    """process_batch must raise if the succeeded batch has no output file."""
    from types import SimpleNamespace

    no_output_job = SimpleNamespace(
        name="batches/789",
        state=SimpleNamespace(name="JOB_STATE_SUCCEEDED"),
        dest=SimpleNamespace(file_name=None),
        create_time=None,
        update_time=None,
        error=None,
    )
    request = ProcessBatchRequest(
        action="process",
        batch_id="batches/789",
        credentials={"gemini": "key"},
        supabase={"url": "https://example.supabase.co", "key": "supabase-key"},
    )
    client = FakeBatchClient(no_output_job)
    service._create_genai_client = lambda api_key: client  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="no output file"):
        asyncio.run(service.process_batch(request))


# ---------------------------------------------------------------------------
# _extract_inline_data
# ---------------------------------------------------------------------------


def test_extract_inline_data_returns_none_for_empty_candidates(service: TTSBatchService):
    assert service._extract_inline_data({"candidates": []}) is None


def test_extract_inline_data_returns_none_when_no_inline_data_in_parts(service: TTSBatchService):
    payload = {"candidates": [{"content": {"parts": [{"text": "some-text"}]}}]}
    assert service._extract_inline_data(payload) is None


def test_extract_inline_data_returns_first_inline_data(service: TTSBatchService):
    inline = {"mimeType": "audio/mpeg", "data": "QUJD"}
    payload = {"candidates": [{"content": {"parts": [{"inlineData": inline}]}}]}
    assert service._extract_inline_data(payload) == inline


# ---------------------------------------------------------------------------
# _aggregate_token_usage
# ---------------------------------------------------------------------------


def test_aggregate_token_usage_skips_items_without_usage(service: TTSBatchService):
    results = [{"id": "a", "token_usage": {"input_tokens": None, "output_tokens": None, "cached_input_tokens": None, "total_tokens": None}}]
    failures: list = []

    aggregate = service._aggregate_token_usage(results, failures)

    assert aggregate["reported_item_count"] == 0
    assert aggregate["total_tokens"] == 0


# ---------------------------------------------------------------------------
# _safe_batch_id
# ---------------------------------------------------------------------------


def test_safe_batch_id_replaces_slashes(service: TTSBatchService):
    assert service._safe_batch_id("batches/abc/123") == "batches_abc_123"


# ---------------------------------------------------------------------------
# _download_file_text
# ---------------------------------------------------------------------------


def test_download_file_text_handles_string_response(service: TTSBatchService):
    class StringClient:
        class files:
            @staticmethod
            def download(*, file):
                return "already a string"

    assert service._download_file_text(StringClient(), "files/x") == "already a string"
