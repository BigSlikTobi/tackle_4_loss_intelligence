#!/bin/bash
# Local testing script for the URL content extraction Cloud Function

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${PORT:-8080}"

echo "Starting local URL content extraction server on http://localhost:${PORT}" 
python3 local_server.py
