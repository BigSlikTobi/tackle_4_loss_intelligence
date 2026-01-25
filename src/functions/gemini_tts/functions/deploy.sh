#!/bin/bash
set -e

# Configuration
FUNCTION_NAME="gemini-tts"
REGION="us-central1"
ENTRY_POINT="generate_speech_http"
RUNTIME="python312"
MEMORY="512MB"

# Get the directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
MODULE_ROOT="$(dirname "$DIR")"
TEMP_DIR=$(mktemp -d)

echo "Deploying $FUNCTION_NAME to $REGION..."
echo "Temp dir: $TEMP_DIR"

# Cleanup trap
trap "rm -rf $TEMP_DIR" EXIT

# Copy files to temp dir
# We need to flatten the structure for Cloud Functions or maintain it carefully.
# The standard python cloud function structure usually expects main.py at root of zip.
# But our imports are like `from ..core.factory`. 
# To make this work in Cloud Functions without complex packaging, 
# we usually copy the necessary code into the temp dir and adjust imports 
# OR we rely on the fact that we upload the whole directory.

# AGENTS.md suggests: "generate temporary main.py/requirements.txt"
# If we upload the whole `src/functions/gemini_tts` folder content?
# Actually, the best way for this isolated module is to copy `core` and `functions/main.py` 
# into the temp root, and adjust imports if necessary. 
# However, if we want to keep relative imports working `from ..core`, 
# we should preserve the structure `src/functions/gemini_tts`.
# Let's try to copy the whole content of `gemini_tts` to `temp` but verify structure.

# Strategy:
# Create a flat structure in temp:
# file: main.py (from functions/main.py)
# dir: core/ (from core/)
# file: requirements.txt

cp "$DIR/main.py" "$TEMP_DIR/main.py"
cp "$MODULE_ROOT/requirements.txt" "$TEMP_DIR/requirements.txt"
cp -r "$MODULE_ROOT/core" "$TEMP_DIR/core"

# Now we need to adjust imports in main.py because `from ..core` won't work 
# if main.py is at the root and core is a sibling.
# We will simple sed replacement to fix imports for the flattened structure.
# `from ..core` -> `from core`
sed -i.bak 's/from \.\.core/from core/g' "$TEMP_DIR/main.py" && rm "$TEMP_DIR/main.py.bak"

# Also checking if core files have relative imports that might break.
# core/service.py imports `from .config`. That works fine within core package.

cd "$TEMP_DIR"

# Deploy
gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --region=$REGION \
    --runtime=$RUNTIME \
    --source=. \
    --entry-point=$ENTRY_POINT \
    --trigger-http \
    --allow-unauthenticated \
    --memory=$MEMORY \
    --set-env-vars LOG_LEVEL=INFO

echo "Deployment complete."
