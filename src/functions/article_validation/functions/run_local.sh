#!/bin/bash
# Local testing script for the article validation Cloud Function

set -e

echo "Starting local article validation server..."
echo ""
echo "Server will listen on http://localhost:8080"
echo "Test with: curl -X POST http://localhost:8080 -H 'Content-Type: application/json' -d @../test_requests/sample_validation.json"
echo ""

cd "$(dirname "$0")"

export PORT=8080
python3 local_server.py
