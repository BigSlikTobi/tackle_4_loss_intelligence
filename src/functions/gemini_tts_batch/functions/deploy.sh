#!/bin/bash
set -e

FUNCTION_NAME="gemini-tts-batch"
REGION="us-central1"
RUNTIME="python312"
ENTRY_POINT="handle_tts_batch"
MEMORY="1024MB"
TIMEOUT="540s"

echo "Deploying $FUNCTION_NAME to $REGION"
echo "Runtime credentials are supplied in each request payload"

cd "$(dirname "$0")"
cd ../../../..

TEMP_DEPLOY_DIR=$(mktemp -d -t gemini-tts-batch-deploy.XXXXXX)

cleanup() {
  if [ -d "$TEMP_DEPLOY_DIR" ]; then
    rm -rf "$TEMP_DEPLOY_DIR"
  fi
}
trap cleanup EXIT

rsync -a --exclude 'venv' --exclude '__pycache__' src/ "$TEMP_DEPLOY_DIR/src/"

cat > "$TEMP_DEPLOY_DIR/main.py" <<'EOF'
"""Deployment entry point for Gemini TTS batch Cloud Function."""

from __future__ import annotations

import flask

from src.functions.gemini_tts_batch.functions.main import handle_tts_batch


def handle_tts_batch_entry(request: flask.Request):
    return handle_tts_batch(request)
EOF

cat > "$TEMP_DEPLOY_DIR/requirements.txt" <<'EOF'
functions-framework>=3.0.0
flask>=3.0.0
pydantic>=2.0.0
httpx>=0.27.0
pydub>=0.25.0
google-genai>=1.0.0
supabase>=2.3.0
EOF

gcloud functions deploy "$FUNCTION_NAME" \
  --gen2 \
  --region="$REGION" \
  --runtime="$RUNTIME" \
  --entry-point="handle_tts_batch_entry" \
  --trigger-http \
  --allow-unauthenticated \
  --memory="$MEMORY" \
  --timeout="$TIMEOUT" \
  --source="$TEMP_DEPLOY_DIR" \
  --set-env-vars="LOG_LEVEL=INFO" \
  --clear-secrets

echo "Deployment complete."
