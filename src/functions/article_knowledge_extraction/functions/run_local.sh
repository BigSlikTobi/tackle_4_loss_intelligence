#!/bin/bash
# Local development server for article_knowledge_extraction.

set -e

cd "$(dirname "$0")"

export PORT="${PORT:-8080}"
echo "Starting article_knowledge_extraction local server on http://localhost:${PORT}"
echo "Endpoints: POST /submit, POST /poll, POST /worker, GET /health"
echo ""

python3 local_server.py
