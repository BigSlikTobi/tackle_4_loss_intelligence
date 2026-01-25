#!/bin/bash
set -e

# Get the directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
MODULE_ROOT="$(dirname "$DIR")"

# Ensure venv is active
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Warning: No virtual environment active. Attempting to activate related venv..."
    # Try looking for venv in module root or project root
    if [ -d "$MODULE_ROOT/venv" ]; then
        source "$MODULE_ROOT/venv/bin/activate"
    elif [ -d "$DIR/../../../../venv" ]; then
        source "$DIR/../../../../venv/bin/activate"
    fi
fi

# Set PYTHONPATH to include the project root so imports like `src.functions...` *could* work
# but our code uses relative imports geared towards the module structure.
# local_server.py does `sys.path.append` logic, but setting PYTHONPATH is safer.
export PYTHONPATH="$DIR/../../../..:$PYTHONPATH"

# Run local server
echo "Starting local server on http://localhost:8080"
python3 "$DIR/local_server.py"
