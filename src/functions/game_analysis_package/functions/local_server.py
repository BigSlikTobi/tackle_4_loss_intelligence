"""
Local development server for game analysis Cloud Function.

This file is ONLY for local testing and should NOT be deployed.
Use run_local.sh to start the server.
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent.parent.absolute()
sys.path.insert(0, str(project_root))

from flask import Flask, request

# Import the Cloud Function handler
from main import analysis_handler

app = Flask(__name__)


@app.route('/', methods=['POST', 'OPTIONS'])
def local_handler():
    """Local development handler that wraps the Cloud Function."""
    return analysis_handler(request)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting local server on http://localhost:{port}")
    print(f"Test with: curl -X POST http://localhost:{port} -H 'Content-Type: application/json' -d @../test_requests/http_api_test_minimal.json")
    print("")
    app.run(host='0.0.0.0', port=port, debug=True)
