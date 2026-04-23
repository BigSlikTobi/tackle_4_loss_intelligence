"""Local development server — routes /submit /poll /worker /health."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from flask import Flask, request

project_root = Path(__file__).resolve().parents[4]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.functions.news_extraction_service.functions.main import (
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
    port = int(os.environ.get("PORT", 8080))
    os.environ.setdefault("WORKER_URL", f"http://localhost:{port}/worker")
    print(f"Starting news_extraction_service local server on http://localhost:{port}")
    print("Endpoints: POST /submit, POST /poll, POST /worker, GET /health")
    app.run(host="0.0.0.0", port=port, debug=True)
