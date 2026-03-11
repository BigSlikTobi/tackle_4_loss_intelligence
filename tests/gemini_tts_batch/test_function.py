import json

from src.functions.gemini_tts_batch.functions.local_server import app


def test_options_request_returns_cors_headers():
    client = app.test_client()

    response = client.open("/", method="OPTIONS")

    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == "*"


def test_invalid_payload_returns_400():
    client = app.test_client()

    response = client.post("/", data="not-json", content_type="application/json")

    assert response.status_code == 400


def test_create_route_dispatches(monkeypatch):
    client = app.test_client()

    async def fake_create_batch(self, request):
        return {"batch_id": "batches/123", "status": "JOB_STATE_RUNNING"}

    monkeypatch.setattr(
        "src.functions.gemini_tts_batch.core.service.TTSBatchService.create_batch",
        fake_create_batch,
    )

    response = client.post(
        "/",
        data=json.dumps(
            {
                "action": "create",
                "model_name": "gemini-2.5-pro-preview-tts",
                "items": [{"id": "story-1", "text": "Hello"}],
                "credentials": {"gemini": "key"},
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["batch_id"] == "batches/123"


def test_status_route_dispatches(monkeypatch):
    client = app.test_client()

    async def fake_check_status(self, request):
        return {"batch_id": "batches/123", "status": "JOB_STATE_RUNNING"}

    monkeypatch.setattr(
        "src.functions.gemini_tts_batch.core.service.TTSBatchService.check_status",
        fake_check_status,
    )

    response = client.post(
        "/",
        data=json.dumps(
            {
                "action": "status",
                "batch_id": "batches/123",
                "credentials": {"gemini": "key"},
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "JOB_STATE_RUNNING"


def test_process_route_dispatches(monkeypatch):
    client = app.test_client()

    async def fake_process_batch(self, request):
        return {"batch_id": "batches/123", "processed_count": 2}

    monkeypatch.setattr(
        "src.functions.gemini_tts_batch.core.service.TTSBatchService.process_batch",
        fake_process_batch,
    )

    response = client.post(
        "/",
        data=json.dumps(
            {
                "action": "process",
                "batch_id": "batches/123",
                "credentials": {"gemini": "key"},
                "supabase": {
                    "url": "https://example.supabase.co",
                    "key": "supabase-key",
                },
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.get_json()["processed_count"] == 2


def test_runtime_error_returns_502(monkeypatch):
    client = app.test_client()

    async def raise_runtime(self, request):
        raise RuntimeError("Upstream Gemini API failed")

    monkeypatch.setattr(
        "src.functions.gemini_tts_batch.core.service.TTSBatchService.check_status",
        raise_runtime,
    )

    response = client.post(
        "/",
        data=json.dumps(
            {
                "action": "status",
                "batch_id": "batches/123",
                "credentials": {"gemini": "key"},
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 502
    assert "Upstream Gemini API failed" in response.get_data(as_text=True)


def test_unexpected_exception_returns_500(monkeypatch):
    client = app.test_client()

    async def raise_unexpected(self, request):
        raise Exception("Something completely unexpected")

    monkeypatch.setattr(
        "src.functions.gemini_tts_batch.core.service.TTSBatchService.check_status",
        raise_unexpected,
    )

    response = client.post(
        "/",
        data=json.dumps(
            {
                "action": "status",
                "batch_id": "batches/123",
                "credentials": {"gemini": "key"},
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 500
    assert "Internal Server Error" in response.get_data(as_text=True)
