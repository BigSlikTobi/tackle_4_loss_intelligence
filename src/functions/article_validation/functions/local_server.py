"""Local development server for the article validation Cloud Function."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from flask import Flask, request

# Ensure project root is on sys.path
project_root = Path(__file__).parent.parent.parent.parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.functions.article_validation.functions.main import article_validation_handler

app = Flask(__name__)


@app.route("/", methods=["POST", "OPTIONS"])
def local_handler():
    """Proxy HTTP requests to the Cloud Function handler."""
    return article_validation_handler(request)


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    from src.functions.article_validation.functions.main import health_check_handler
    return health_check_handler(request)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting local article validation server on http://localhost:{port}")
    print(
        "Test with: curl -X POST http://localhost:{port} -H 'Content-Type: application/json' -d @../test_requests/sample_validation.json".replace(
            "{port}", str(port)
        )
    )
    print("")
    app.run(host="0.0.0.0", port=port, debug=True)
