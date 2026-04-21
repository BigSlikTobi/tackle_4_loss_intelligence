#!/bin/bash
# Local testing script for the news extraction Cloud Function

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${PORT:-8080}"

echo "Starting local news extraction server on http://localhost:${PORT}"
python3 local_server.py
