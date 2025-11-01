#!/bin/bash
# Deployment script for the image selection Cloud Function

set -e

# Configuration
FUNCTION_NAME="image-selection"
REGION="us-central1"
RUNTIME="python312"
ENTRY_POINT="select_article_images"
MEMORY="1024MB"
TIMEOUT="540s"

# Output colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo ""
info "Deploying image selection Cloud Function..."
echo ""
info "Configuration:"
echo "  Function: $FUNCTION_NAME"
echo "  Region:   $REGION"
echo "  Runtime:  $RUNTIME"
echo "  Memory:   $MEMORY"
echo "  Timeout:  $TIMEOUT"
echo ""

# Ensure we are in the functions directory
cd "$(dirname "$0")"

if ! command -v gcloud >/dev/null 2>&1; then
  error "gcloud CLI not found. Install the Cloud SDK first."
  echo "See: https://cloud.google.com/sdk/docs/install"
  exit 1
fi

if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | grep -q .; then
  error "No active gcloud account. Run 'gcloud auth login' first."
  exit 1
fi

PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT_ID" ]; then
  error "No GCP project configured. Run 'gcloud config set project PROJECT_ID' first."
  exit 1
fi

info "Deploying to project: $PROJECT_ID"
echo ""
info "Deployment will include the entire src/ tree for proper imports"
info "Runtime credentials are supplied in each request payload (no Secret Manager entries required)"

# Move to project root (functions -> image_selection -> functions -> src -> root)
cd ../../../..

info "Deploying from: $(pwd)"

if [ ! -d "src" ]; then
  error "src/ directory not found. Are we in the project root?"
  exit 1
fi

# Create temporary deployment directory
TEMP_DEPLOY_DIR=$(mktemp -d -t image-selection-deploy.XXXXXX)
info "Created temporary deployment directory: $TEMP_DEPLOY_DIR"

# Ensure cleanup happens even if deployment fails
cleanup() {
  if [ -d "$TEMP_DEPLOY_DIR" ]; then
    info "Cleaning up temporary deployment directory..."
    rm -rf "$TEMP_DEPLOY_DIR"
  fi
}
trap cleanup EXIT

# Copy entire src/ directory to temp location
info "Copying source files to temporary directory..."
cp -r src "$TEMP_DEPLOY_DIR/"

info "Creating deployment entry point..."
cat > "$TEMP_DEPLOY_DIR/main.py" <<'EOF'
"""Deployment entry point for image_selection Cloud Function."""

from __future__ import annotations

import flask

from src.functions.image_selection.functions.main import (
    image_selection_handler,
    health_check_handler,
)


def select_article_images(request: flask.Request):
    return image_selection_handler(request)


def health_check(request: flask.Request):
    return health_check_handler(request)
EOF
info "Entry point created"

info "Creating requirements.txt..."
cat > "$TEMP_DEPLOY_DIR/requirements.txt" <<'EOF'
# Cloud Function Dependencies
functions-framework==3.*
flask==3.*

# Service dependencies
aiohttp>=3.9.0
certifi>=2023.7.22
duckduckgo-search>=4.4.3
supabase>=2.0.0
google-generativeai>=0.8.0
openai>=1.12.0
python-dotenv>=1.0.0
EOF
info "Requirements file created"
echo ""

info "Deploying function from temporary directory..."
gcloud functions deploy "$FUNCTION_NAME" \
  --gen2 \
  --region="$REGION" \
  --runtime="$RUNTIME" \
  --entry-point="$ENTRY_POINT" \
  --trigger-http \
  --allow-unauthenticated \
  --memory="$MEMORY" \
  --timeout="$TIMEOUT" \
  --source="$TEMP_DEPLOY_DIR" \
  --set-env-vars="LOG_LEVEL=INFO" \
  --clear-secrets

# Cleanup handled by trap

echo ""
info "✓ Deployment complete!"
echo ""
CALL_URL=$(gcloud functions describe "$FUNCTION_NAME" --region="$REGION" --gen2 --format="value(serviceConfig.uri)")
if [ -n "$CALL_URL" ]; then
  echo "Function URL: $CALL_URL"
  echo ""
  echo "Test with:"
  echo "curl -X POST ${CALL_URL} \\
    -H 'Content-Type: application/json' \\
    -d '{\"article_text\": \"Your article text\", \"num_images\": 2}'"
else
  warn "Unable to fetch function URL automatically."
fi