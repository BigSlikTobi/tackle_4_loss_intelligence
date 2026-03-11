#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
MODULE_ROOT="$(dirname "$DIR")"

if [ -z "$VIRTUAL_ENV" ]; then
    echo "Warning: No virtual environment active. Attempting to activate module venv..."
    if [ -d "$MODULE_ROOT/venv" ]; then
        source "$MODULE_ROOT/venv/bin/activate"
    fi
fi

export PYTHONPATH="$DIR/../../../..:$PYTHONPATH"

echo "Starting Gemini TTS batch server on http://localhost:8080"
python3 "$DIR/local_server.py"
