#!/bin/bash
set -e

# Configuration
FUNCTION_NAME="youtube-search"
REGION="us-central1"
ENTRY_POINT="youtube_search_http"
RUNTIME="python312"
MEMORY="256MB"

# Get the directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
MODULE_ROOT="$(dirname "$DIR")"
TEMP_DIR=$(mktemp -d)

echo "Deploying $FUNCTION_NAME to $REGION..."
echo "Temp dir: $TEMP_DIR"

# Cleanup trap
trap "rm -rf $TEMP_DIR" EXIT

# Strategy:
# Create a flat structure in temp:
# file: main.py (from functions/main.py)
# dir: core/ (from core/)
# file: requirements.txt

cp "$DIR/main.py" "$TEMP_DIR/main.py"
cp "$MODULE_ROOT/requirements.txt" "$TEMP_DIR/requirements.txt"
cp -r "$MODULE_ROOT/core" "$TEMP_DIR/core"

# Adjust imports in main.py for the flattened structure
# `from ..core` -> `from core`
sed -i '' 's/from \.\.core/from core/g' "$TEMP_DIR/main.py"

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
echo ""
echo "Note: YouTube API credentials are supplied within each request."
echo "Function URL: https://$REGION-$(gcloud config get-value project).cloudfunctions.net/$FUNCTION_NAME"
