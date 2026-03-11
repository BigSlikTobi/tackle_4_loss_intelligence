import pytest

from src.functions.gemini_tts_batch.core.config import (
    CreateBatchRequest,
    ProcessBatchRequest,
    StatusBatchRequest,
)
from src.functions.gemini_tts_batch.core.factory import TTSBatchFactory


def test_factory_builds_create_request():
    payload = {
        "action": "create",
        "model_name": "gemini-2.5-pro-preview-tts",
        "items": [{"id": "story-1", "text": "Hello world"}],
        "credentials": {"gemini": "key"},
    }

    request = TTSBatchFactory.create_request(payload)

    assert isinstance(request, CreateBatchRequest)
    assert request.voice_name == "Charon"


def test_factory_builds_status_request():
    request = TTSBatchFactory.create_request(
        {
            "action": "status",
            "batch_id": "batches/123",
            "credentials": {"gemini": "key"},
        }
    )

    assert isinstance(request, StatusBatchRequest)


def test_factory_builds_process_request():
    request = TTSBatchFactory.create_request(
        {
            "action": "process",
            "batch_id": "batches/123",
            "credentials": {"gemini": "key"},
            "supabase": {
                "url": "https://example.supabase.co",
                "key": "supabase-key",
            },
        }
    )

    assert isinstance(request, ProcessBatchRequest)
    assert request.supabase.bucket == "audio"


def test_factory_rejects_duplicate_item_ids():
    with pytest.raises(ValueError, match="unique ids"):
        TTSBatchFactory.create_request(
            {
                "action": "create",
                "model_name": "gemini-2.5-pro-preview-tts",
                "items": [
                    {"id": "story-1", "text": "first"},
                    {"id": "story-1", "text": "second"},
                ],
                "credentials": {"gemini": "key"},
            }
        )


def test_factory_rejects_empty_items():
    with pytest.raises(ValueError, match="at least one item"):
        TTSBatchFactory.create_request(
            {
                "action": "create",
                "model_name": "gemini-2.5-pro-preview-tts",
                "items": [],
                "credentials": {"gemini": "key"},
            }
        )


def test_factory_requires_action():
    with pytest.raises(ValueError, match="action must be one of"):
        TTSBatchFactory.create_request({})


def test_factory_accepts_structured_script_payload():
    payload = {
        "action": "create",
        "model_name": "gemini-2.5-pro-preview-tts",
        "items": [
            {
                "id": "story-1",
                "title": "Breaking news",
                "direction": {
                    "audio_profile": "Live breaking NFL hit",
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
        "credentials": {"gemini": "key"},
    }

    request = TTSBatchFactory.create_request(payload)

    assert isinstance(request, CreateBatchRequest)
    assert request.items[0].script.body == "Body text"
    assert request.items[0].direction.pronunciations[0].term == "Tagovailoa"


def test_factory_allows_missing_credentials_for_env_fallback():
    request = TTSBatchFactory.create_request(
        {
            "action": "status",
            "batch_id": "batches/123",
        }
    )

    assert isinstance(request, StatusBatchRequest)
    assert request.credentials is None


def test_factory_rejects_item_with_no_content():
    """BatchItem requires at least one of text, tts_prompt, or script."""
    with pytest.raises(ValueError, match="text, tts_prompt, or script"):
        TTSBatchFactory.create_request(
            {
                "action": "create",
                "model_name": "gemini-2.5-pro-preview-tts",
                "items": [{"id": "story-1", "title": "Title only, no content"}],
                "credentials": {"gemini": "key"},
            }
        )


def test_factory_rejects_pronunciation_as_plain_string():
    """Regression: pronunciations must be {term, guide} objects, not bare strings."""
    with pytest.raises(ValueError, match="PronunciationGuide"):
        TTSBatchFactory.create_request(
            {
                "action": "create",
                "model_name": "gemini-2.5-pro-preview-tts",
                "items": [
                    {
                        "id": "story-1",
                        "text": "Hello world",
                        "direction": {
                            "pronunciations": ["GEE-no Smith"]
                        },
                    }
                ],
                "credentials": {"gemini": "key"},
            }
        )


def test_factory_rejects_script_with_no_sections():
    """TTSScript must contain at least one of intro, body, or outro."""
    with pytest.raises(ValueError, match="at least one of intro, body, or outro"):
        TTSBatchFactory.create_request(
            {
                "action": "create",
                "model_name": "gemini-2.5-pro-preview-tts",
                "items": [
                    {
                        "id": "story-1",
                        "script": {},
                    }
                ],
                "credentials": {"gemini": "key"},
            }
        )


def test_factory_accepts_tts_prompt_as_item_content():
    """tts_prompt is a valid content field for a BatchItem."""
    request = TTSBatchFactory.create_request(
        {
            "action": "create",
            "model_name": "gemini-2.5-pro-preview-tts",
            "items": [
                {
                    "id": "story-1",
                    "tts_prompt": "<speak>Hello world</speak>",
                }
            ],
            "credentials": {"gemini": "key"},
        }
    )

    assert isinstance(request, CreateBatchRequest)
    assert request.items[0].tts_prompt == "<speak>Hello world</speak>"


def test_factory_rejects_non_dict_payload():
    """Payload must be a JSON object, not a list or scalar."""
    with pytest.raises(ValueError, match="JSON object"):
        TTSBatchFactory.create_request(["not", "a", "dict"])  # type: ignore[arg-type]
