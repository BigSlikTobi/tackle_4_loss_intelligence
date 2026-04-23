#!/bin/bash
# Launch the news_extraction service locally on port 8080.
set -e
cd "$(dirname "$0")"
PORT="${PORT:-8080}" exec python local_server.py
