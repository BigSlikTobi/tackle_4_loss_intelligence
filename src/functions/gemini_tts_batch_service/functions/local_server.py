"""Local development server — routes /submit /poll /worker /health to handlers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from flask import Flask, request

project_root = Path(__file__).resolve().parents[4]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# IMPORTANT: ``main.py`` snapshots ``WORKER_URL`` at import time. Set it
# BEFORE importing the handlers, otherwise local /submit logs
# "WORKER_URL not configured" and the worker self-invoke never fires.
_PORT = int(os.environ.get("PORT", 8080))
os.environ.setdefault("WORKER_URL", f"http://localhost:{_PORT}/worker")

from src.functions.gemini_tts_batch_service.functions.main import (  # noqa: E402
    health_check_handler,
    poll_handler,
    submit_handler,
    worker_handler,
)

app = Flask(__name__)


@app.route("/submit", methods=["POST", "OPTIONS"])
def _submit():
    return submit_handler(request)


@app.route("/poll", methods=["POST", "OPTIONS"])
def _poll():
    return poll_handler(request)


@app.route("/worker", methods=["POST"])
def _worker():
    return worker_handler(request)


@app.route("/health", methods=["GET"])
def _health():
    return health_check_handler(request)


if __name__ == "__main__":
    print(f"Starting gemini_tts_batch_service local server on http://localhost:{_PORT}")
    print("Endpoints: POST /submit, POST /poll, POST /worker, GET /health")
    app.run(host="0.0.0.0", port=_PORT, debug=True)
