"""Local development server for the image selection Cloud Function."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from flask import Flask, request

# Ensure project root is on sys.path
project_root = Path(__file__).parent.parent.parent.parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.functions.image_selection.functions.main import image_selection_handler

app = Flask(__name__)


@app.route("/", methods=["POST", "OPTIONS"])
def local_handler():
    """Proxy HTTP requests to the Cloud Function handler."""
    return image_selection_handler(request)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting local image selection server on http://localhost:{port}")
    print(
        "Test with: curl -X POST http://localhost:{port} -H 'Content-Type: application/json' -d @../test_requests/sample_request.json".replace(
            "{port}", str(port)
        )
    )
    print("")
    app.run(host="0.0.0.0", port=port, debug=True)
