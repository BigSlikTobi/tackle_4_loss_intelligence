"""Local development server for the URL content extraction Cloud Function."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

from flask import Flask, Request, make_response, request

project_root = Path(__file__).parent.parent.parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.functions.url_content_extraction.functions.main import handle_request

app = Flask(__name__)


def _cors_response(body: Dict[str, Any] | list[Any], status: int = 200):
    response = make_response(json.dumps(body, ensure_ascii=False), status)
    headers = response.headers
    headers["Content-Type"] = "application/json"
    headers["Access-Control-Allow-Origin"] = "*"
    headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
    headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return response


@app.route("/", methods=["POST", "OPTIONS"])
def local_handler():
    """Proxy HTTP requests to the module handler for local testing."""

    if request.method == "OPTIONS":
        return _cors_response({}, status=204)

    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    result = handle_request(payload)
    return _cors_response(result)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"Starting URL content extraction server on http://localhost:{port}")
    print(
        "Test with: curl -X POST http://localhost:{port} -H 'Content-Type: application/json' -d @../test_requests/sample_request.json".replace(
            "{port}", str(port)
        )
    )
    print("")
    app.run(host="0.0.0.0", port=port, debug=True)
