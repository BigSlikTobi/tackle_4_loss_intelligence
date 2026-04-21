#!/bin/bash
# Deployment script for the news extraction Cloud Function.
#
# Callers may pass optional `supabase` credentials in the request payload;
# `--clear-secrets` ensures we do not rely on Secret Manager entries from prior
# deployments.

set -euo pipefail

FUNCTION_NAME="news-extraction"
REGION="us-central1"
RUNTIME="python312"
ENTRY_POINT="news_extractor"
MEMORY="512MB"
TIMEOUT="540s"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

info "Preparing deployment for ${FUNCTION_NAME}"

if [ ! -d "${PROJECT_ROOT}/src" ]; then
  error "Unable to locate project root. Expected src/ directory at ${PROJECT_ROOT}."
  exit 1
fi

if ! command -v gcloud >/dev/null 2>&1; then
  error "gcloud CLI not found. Install the Cloud SDK first."
  exit 1
fi

ACTIVE_ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)")
if [ -z "$ACTIVE_ACCOUNT" ]; then
  error "No active gcloud account. Run 'gcloud auth login' first."
  exit 1
fi

PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT_ID" ]; then
  error "No GCP project configured. Run 'gcloud config set project PROJECT_ID'."
  exit 1
fi

info "Deploying to project: ${PROJECT_ID} (account: ${ACTIVE_ACCOUNT})"

cd "$PROJECT_ROOT"

# Temporary deployment directory (auto-cleaned on exit)
TEMP_DEPLOY_DIR=$(mktemp -d -t news-extraction-deploy.XXXXXX)
info "Created temporary deployment directory: $TEMP_DEPLOY_DIR"

cleanup() {
  if [ -n "$TEMP_DEPLOY_DIR" ] && [ -d "$TEMP_DEPLOY_DIR" ]; then
    info "Cleaning up temporary directory: $TEMP_DEPLOY_DIR"
    rm -rf "$TEMP_DEPLOY_DIR"
  fi
}
trap cleanup EXIT

info "Copying source code to temporary directory"
cp -r src "$TEMP_DEPLOY_DIR/"

info "Generating deployment entry point wrapper"
cat > "$TEMP_DEPLOY_DIR/main.py" <<'EOF'
"""Deployment wrapper for the news extraction Cloud Function."""

from __future__ import annotations

import sys
from pathlib import Path

import flask

project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.functions.news_extraction.functions.main import news_extractor


def news_extractor_handler(request: flask.Request) -> flask.Response:
    return news_extractor(request)
EOF

info "Creating requirements.txt"
cat > "$TEMP_DEPLOY_DIR/requirements.txt" <<'EOF'
functions-framework==3.*
flask==3.*
python-dotenv>=1.0.0
PyYAML>=6.0.0
feedparser>=6.0.0
python-dateutil>=2.8.0
requests>=2.31.0
lxml>=4.9.0
supabase>=2.0.0
EOF

info "Deploying Cloud Function"
gcloud functions deploy "${FUNCTION_NAME}" \
  --gen2 \
  --region="${REGION}" \
  --runtime="${RUNTIME}" \
  --entry-point="news_extractor_handler" \
  --trigger-http \
  --allow-unauthenticated \
  --memory="${MEMORY}" \
  --timeout="${TIMEOUT}" \
  --source="$TEMP_DEPLOY_DIR" \
  --set-env-vars="LOG_LEVEL=INFO" \
  --clear-secrets

info "Deployment complete. Credentials are expected in each request's 'supabase' block."

FUNCTION_URL=$(gcloud functions describe "${FUNCTION_NAME}" --region="${REGION}" --gen2 --format="value(serviceConfig.uri)")
if [ -n "$FUNCTION_URL" ]; then
  echo ""
  info "Function URL: ${FUNCTION_URL}"
  echo "Test with:"
  echo "curl -X POST ${FUNCTION_URL} \\
    -H 'Content-Type: application/json' \\
    -d '{\"dry_run\": true}'"
else
  warn "Unable to fetch function URL automatically."
fi
