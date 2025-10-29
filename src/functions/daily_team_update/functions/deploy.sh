#!/bin/bash
# Deployment script for the daily team update Cloud Function

set -euo pipefail

FUNCTION_NAME="daily-team-update"
REGION="us-central1"
RUNTIME="python312"
ENTRY_POINT="run_pipeline"
MEMORY="2048MB"
TIMEOUT="540s"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

info "Preparing deployment for ${FUNCTION_NAME}"

dirname "${BASH_SOURCE[0]}" >/dev/null 2>&1 || {
  error "Unable to determine script location"
  exit 1
}

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd "${SCRIPT_DIR}/../../../.." && pwd)

if [ ! -d "${PROJECT_ROOT}/src" ]; then
  error "Unable to locate project root from ${SCRIPT_DIR}"
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

info "Generating temporary deployment entry point"
cat > main.py <<'EOF'
"""Deployment wrapper for the daily team update Cloud Function."""

from __future__ import annotations

import flask

from src.functions.daily_team_update.functions.main import pipeline_handler, health_check_handler


def run_pipeline(request: flask.Request):
    return pipeline_handler(request)


def health_check(request: flask.Request):
    return health_check_handler(request)
EOF

info "Generating temporary requirements.txt"
cat > requirements.txt <<'EOF'
# Cloud Function dependencies
functions-framework==3.*
flask==3.*
httpx>=0.26.0
supabase>=2.0.0
pydantic>=2.6.0
python-dotenv>=1.0.0
EOF

info "Deploying Cloud Function..."
gcloud functions deploy "${FUNCTION_NAME}" \
  --gen2 \
  --region="${REGION}" \
  --runtime="${RUNTIME}" \
  --entry-point="${ENTRY_POINT}" \
  --trigger-http \
  --allow-unauthenticated \
  --memory="${MEMORY}" \
  --timeout="${TIMEOUT}" \
  --source=. \
  --set-env-vars="LOG_LEVEL=INFO" \
  --clear-secrets

info "Cleaning up temporary files"
rm -f main.py requirements.txt

info "Deployment complete"

FUNCTION_URL=$(gcloud functions describe "${FUNCTION_NAME}" --region="${REGION}" --gen2 --format="value(serviceConfig.uri)")
if [ -n "$FUNCTION_URL" ]; then
  echo ""
  info "Function URL: ${FUNCTION_URL}"
  echo "Invoke with:"
  echo "curl -X POST ${FUNCTION_URL} \\
    -H 'Content-Type: application/json' \\
    -d '{"parallel": false, "dry_run": true}'"
else
  warn "Unable to fetch function URL automatically."
fi
