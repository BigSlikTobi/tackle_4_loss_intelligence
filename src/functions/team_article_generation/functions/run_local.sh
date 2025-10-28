#!/bin/bash
# Local testing script for the team article generation Cloud Function

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${PORT:-8080}"

echo "Starting local team article generation server on http://localhost:${PORT}" 
python3 local_server.py
