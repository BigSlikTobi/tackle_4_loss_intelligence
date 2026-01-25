#!/bin/bash
set -e

# Get the directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
MODULE_ROOT="$(dirname "$DIR")"

# Prioritize module-specific venv
if [ -d "$MODULE_ROOT/venv" ]; then
    echo "Activating module-specific virtual environment..."
    source "$MODULE_ROOT/venv/bin/activate"
elif [ -z "$VIRTUAL_ENV" ]; then
    echo "Warning: No virtual environment active. Attempting to activate project-level venv..."
    if [ -d "$DIR/../../../../venv" ]; then
        source "$DIR/../../../../venv/bin/activate"
    fi
fi

# Set PYTHONPATH to include the project root so imports like `src.functions...` work
export PYTHONPATH="$DIR/../../../..:$PYTHONPATH"

# Run local server
echo "Starting local server on http://localhost:8080"
python3 "$DIR/local_server.py"
