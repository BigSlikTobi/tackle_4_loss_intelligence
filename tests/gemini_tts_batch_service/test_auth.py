"""Verify the /worker handler enforces X-Worker-Token via constant-time compare."""

from __future__ import annotations

import importlib
from typing import Any, Dict, Optional
from unittest.mock import patch

import flask
import pytest


@pytest.fixture
def app():
    return flask.Flask(__name__)


@pytest.fixture
def fake_request():
    class _Headers(dict):
        def get(self, key, default=""):
            return super().get(key, default)

    class _Request:
        method = "POST"

        def __init__(self, json_body: Dict[str, Any], token: Optional[str]):
            self._json = json_body
            self.headers = _Headers()
            if token is not None:
                self.headers["X-Worker-Token"] = token

        def get_json(self, silent: bool = False):
            return self._json

    return _Request


def _payload() -> Dict[str, Any]:
    return {"job_id": "abc", "supabase": {"url": "u", "key": "k"}}


def _reload_main(monkeypatch):
    # Worker request validation requires the supabase URL + key — both
    # hydrated from env (caller-supplied URLs are ignored, see factory.py).
    monkeypatch.setenv("SUPABASE_URL", "https://env.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    from src.functions.gemini_tts_batch_service.functions import main as mod

    importlib.reload(mod)
    return mod


def test_worker_rejects_missing_token(monkeypatch, app, fake_request):
    monkeypatch.setenv("WORKER_TOKEN", "secret")
    mod = _reload_main(monkeypatch)
    with app.app_context():
        response = mod.worker_handler(fake_request(_payload(), token=None))
    assert response.status_code == 403


def test_worker_rejects_wrong_token(monkeypatch, app, fake_request):
    monkeypatch.setenv("WORKER_TOKEN", "secret")
    mod = _reload_main(monkeypatch)
    with app.app_context():
        response = mod.worker_handler(fake_request(_payload(), token="nope"))
    assert response.status_code == 403


def test_worker_skips_auth_when_env_unset(monkeypatch, app, fake_request):
    monkeypatch.delenv("WORKER_TOKEN", raising=False)
    mod = _reload_main(monkeypatch)
    with patch.object(mod, "run_job", return_value={"job_id": "abc", "status": "noop"}):
        with app.app_context():
            response = mod.worker_handler(fake_request(_payload(), token=None))
    assert response.status_code == 200


def test_worker_accepts_correct_token(monkeypatch, app, fake_request):
    monkeypatch.setenv("WORKER_TOKEN", "secret")
    mod = _reload_main(monkeypatch)
    with patch.object(mod, "run_job", return_value={"job_id": "abc", "status": "noop"}):
        with app.app_context():
            response = mod.worker_handler(fake_request(_payload(), token="secret"))
    assert response.status_code == 200
