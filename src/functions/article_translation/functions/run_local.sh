#!/bin/bash
# Local testing script for the article translation Cloud Function

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${PORT:-8080}"

echo "Starting local article translation server on http://localhost:${PORT}" 
python3 local_server.py
